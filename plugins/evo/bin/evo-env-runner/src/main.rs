//! A small, dependency-free JSONL environment runner.
//!
//! The protocol is intentionally argv-oriented: commands are never passed to
//! a shell. A prepared manifest confines all filesystem paths to `root`, and
//! every response is one compact JSON object so the runner can be supervised
//! by a line-oriented parent process.

use std::collections::BTreeMap;
use std::fs;
use std::io::{self, BufRead, Read, Write};
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

const DEFAULT_TIMEOUT_MS: u64 = 30_000;
const MAX_TIMEOUT_MS: u64 = 86_400_000;
const MAX_ARG_BYTES: usize = 4096;
const MAX_OUTPUT_BYTES: usize = 1_048_576;
const ATTESTATION_FILE: &str = ".evo-env-attestation.json";
const PROTOCOL_VERSION: u64 = 1;

#[derive(Debug, Clone, PartialEq)]
enum JsonValue {
    Null,
    Bool(bool),
    Number(String),
    String(String),
    Array(Vec<JsonValue>),
    Object(BTreeMap<String, JsonValue>),
}

impl JsonValue {
    fn object(entries: impl IntoIterator<Item = (String, JsonValue)>) -> Self {
        Self::Object(entries.into_iter().collect())
    }

    fn string(value: impl Into<String>) -> Self {
        Self::String(value.into())
    }

    fn as_str(&self) -> Option<&str> {
        match self {
            Self::String(value) => Some(value),
            _ => None,
        }
    }

    fn as_object(&self) -> Option<&BTreeMap<String, JsonValue>> {
        match self {
            Self::Object(value) => Some(value),
            _ => None,
        }
    }

    fn as_array(&self) -> Option<&[JsonValue]> {
        match self {
            Self::Array(value) => Some(value),
            _ => None,
        }
    }

    fn as_u64(&self) -> Option<u64> {
        match self {
            Self::Number(value) => value.parse().ok(),
            _ => None,
        }
    }
}

fn json_string(value: &str) -> String {
    let mut out = String::with_capacity(value.len() + 2);
    out.push('"');
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            ch if ch.is_control() => out.push_str(&format!("\\u{:04x}", ch as u32)),
            ch => out.push(ch),
        }
    }
    out.push('"');
    out
}

fn render_json(value: &JsonValue) -> String {
    match value {
        JsonValue::Null => "null".to_owned(),
        JsonValue::Bool(value) => value.to_string(),
        JsonValue::Number(value) => value.clone(),
        JsonValue::String(value) => json_string(value),
        JsonValue::Array(values) => format!(
            "[{}]",
            values.iter().map(render_json).collect::<Vec<_>>().join(",")
        ),
        JsonValue::Object(values) => values
            .iter()
            .map(|(key, value)| format!("{}:{}", json_string(key), render_json(value)))
            .collect::<Vec<_>>()
            .join(",")
            .pipe(|body| format!("{{{body}}}")),
    }
}

// A tiny helper to keep render_json readable without importing a utility crate.
trait Pipe: Sized {
    fn pipe<T>(self, f: impl FnOnce(Self) -> T) -> T {
        f(self)
    }
}
impl<T> Pipe for T {}

struct JsonParser<'a> {
    input: &'a [u8],
    index: usize,
}

impl<'a> JsonParser<'a> {
    fn new(input: &'a str) -> Self {
        Self {
            input: input.as_bytes(),
            index: 0,
        }
    }

    fn parse(mut self) -> Result<JsonValue, String> {
        let value = self.value()?;
        self.ws();
        if self.index != self.input.len() {
            return Err("trailing JSON data".to_owned());
        }
        Ok(value)
    }

    fn value(&mut self) -> Result<JsonValue, String> {
        self.ws();
        match self.peek() {
            Some(b'n') => self.literal(b"null", JsonValue::Null),
            Some(b't') => self.literal(b"true", JsonValue::Bool(true)),
            Some(b'f') => self.literal(b"false", JsonValue::Bool(false)),
            Some(b'"') => Ok(JsonValue::String(self.string()?)),
            Some(b'[') => self.array(),
            Some(b'{') => self.object(),
            Some(b'-' | b'0'..=b'9') => self.number(),
            Some(_) => Err(format!("unexpected JSON byte at {}", self.index)),
            None => Err("unexpected end of JSON".to_owned()),
        }
    }

    fn literal(&mut self, literal: &[u8], value: JsonValue) -> Result<JsonValue, String> {
        if self.input.get(self.index..self.index + literal.len()) == Some(literal) {
            self.index += literal.len();
            Ok(value)
        } else {
            Err(format!("invalid JSON literal at {}", self.index))
        }
    }

    fn object(&mut self) -> Result<JsonValue, String> {
        self.expect(b'{')?;
        let mut object = BTreeMap::new();
        self.ws();
        if self.take_if(b'}') {
            return Ok(JsonValue::Object(object));
        }
        loop {
            self.ws();
            if self.peek() != Some(b'"') {
                return Err(format!("object key must be a string at {}", self.index));
            }
            let key = self.string()?;
            self.ws();
            self.expect(b':')?;
            let value = self.value()?;
            if object.insert(key, value).is_some() {
                return Err("duplicate JSON object key".to_owned());
            }
            self.ws();
            if self.take_if(b'}') {
                return Ok(JsonValue::Object(object));
            }
            self.expect(b',')?;
        }
    }

    fn array(&mut self) -> Result<JsonValue, String> {
        self.expect(b'[')?;
        let mut values = Vec::new();
        self.ws();
        if self.take_if(b']') {
            return Ok(JsonValue::Array(values));
        }
        loop {
            values.push(self.value()?);
            self.ws();
            if self.take_if(b']') {
                return Ok(JsonValue::Array(values));
            }
            self.expect(b',')?;
        }
    }

    fn string(&mut self) -> Result<String, String> {
        self.expect(b'"')?;
        let mut output = String::new();
        loop {
            let byte = self
                .take()
                .ok_or_else(|| "unterminated JSON string".to_owned())?;
            match byte {
                b'"' => return Ok(output),
                b'\\' => {
                    let escape = self.take().ok_or_else(|| "truncated escape".to_owned())?;
                    match escape {
                        b'"' => output.push('"'),
                        b'\\' => output.push('\\'),
                        b'/' => output.push('/'),
                        b'b' => output.push('\u{08}'),
                        b'f' => output.push('\u{0c}'),
                        b'n' => output.push('\n'),
                        b'r' => output.push('\r'),
                        b't' => output.push('\t'),
                        b'u' => {
                            let code = self.hex_u16()?;
                            let ch = char::from_u32(code as u32)
                                .ok_or_else(|| "invalid unicode escape".to_owned())?;
                            if (0xd800..=0xdfff).contains(&code) {
                                return Err("unicode surrogate escapes are unsupported".to_owned());
                            }
                            output.push(ch);
                        }
                        _ => return Err("invalid JSON escape".to_owned()),
                    }
                }
                byte if byte < 0x20 => return Err("control character in JSON string".to_owned()),
                byte => {
                    let start = self.index - 1;
                    let width = utf8_width(byte).ok_or_else(|| "invalid UTF-8".to_owned())?;
                    let end = start + width;
                    if end > self.input.len() {
                        return Err("truncated UTF-8 in JSON string".to_owned());
                    }
                    let text = std::str::from_utf8(&self.input[start..end])
                        .map_err(|_| "invalid UTF-8 in JSON string".to_owned())?;
                    output.push_str(text);
                    self.index = end;
                }
            }
        }
    }

    fn hex_u16(&mut self) -> Result<u16, String> {
        let mut value = 0u16;
        for _ in 0..4 {
            let byte = self
                .take()
                .ok_or_else(|| "truncated unicode escape".to_owned())?;
            value = value
                .checked_mul(16)
                .and_then(|v| v.checked_add(hex_value(byte)?))
                .ok_or_else(|| "unicode escape overflow".to_owned())?;
        }
        Ok(value)
    }

    fn number(&mut self) -> Result<JsonValue, String> {
        let start = self.index;
        self.take_if(b'-');
        if self.take_if(b'0') {
            if self.peek().is_some_and(|byte| byte.is_ascii_digit()) {
                return Err("leading zero in JSON number".to_owned());
            }
        } else {
            self.take_digits(false)?;
        }
        if self.take_if(b'.') {
            self.take_digits(false)?;
        }
        if self.peek().is_some_and(|byte| matches!(byte, b'e' | b'E')) {
            self.index += 1;
            if self.peek().is_some_and(|byte| matches!(byte, b'+' | b'-')) {
                self.index += 1;
            }
            self.take_digits(false)?;
        }
        Ok(JsonValue::Number(
            String::from_utf8(self.input[start..self.index].to_vec())
                .map_err(|_| "invalid JSON number".to_owned())?,
        ))
    }

    fn take_digits(&mut self, allow_empty: bool) -> Result<(), String> {
        let start = self.index;
        while self.peek().is_some_and(|byte| byte.is_ascii_digit()) {
            self.index += 1;
        }
        if !allow_empty && self.index == start {
            return Err("expected JSON number digits".to_owned());
        }
        Ok(())
    }

    fn ws(&mut self) {
        while self
            .peek()
            .is_some_and(|byte| matches!(byte, b' ' | b'\n' | b'\r' | b'\t'))
        {
            self.index += 1;
        }
    }

    fn expect(&mut self, expected: u8) -> Result<(), String> {
        if self.take_if(expected) {
            Ok(())
        } else {
            Err(format!("expected {:?} at {}", expected as char, self.index))
        }
    }

    fn take_if(&mut self, expected: u8) -> bool {
        if self.peek() == Some(expected) {
            self.index += 1;
            true
        } else {
            false
        }
    }

    fn take(&mut self) -> Option<u8> {
        let value = self.peek()?;
        self.index += 1;
        Some(value)
    }

    fn peek(&self) -> Option<u8> {
        self.input.get(self.index).copied()
    }
}

fn utf8_width(byte: u8) -> Option<usize> {
    match byte {
        0x00..=0x7f => Some(1),
        0xc2..=0xdf => Some(2),
        0xe0..=0xef => Some(3),
        0xf0..=0xf4 => Some(4),
        _ => None,
    }
}

fn hex_value(byte: u8) -> Option<u16> {
    match byte {
        b'0'..=b'9' => Some((byte - b'0') as u16),
        b'a'..=b'f' => Some((byte - b'a' + 10) as u16),
        b'A'..=b'F' => Some((byte - b'A' + 10) as u16),
        _ => None,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Manifest {
    schema_version: u64,
    id: String,
    mode: Mode,
    root: PathBuf,
    workdir: String,
    argv: Vec<String>,
    env: BTreeMap<String, String>,
    image: Option<String>,
    timeout_ms: u64,
    outputs: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Mode {
    Host,
    Docker,
}

impl Mode {
    fn as_str(self) -> &'static str {
        match self {
            Self::Host => "host",
            Self::Docker => "docker",
        }
    }
}

fn parse_manifest(value: &JsonValue) -> Result<Manifest, String> {
    let object = value
        .as_object()
        .ok_or_else(|| "manifest must be a JSON object".to_owned())?;
    let schema_version = object
        .get("schema_version")
        .and_then(JsonValue::as_u64)
        .unwrap_or(1);
    if schema_version != 1 {
        return Err("unsupported manifest schema_version".to_owned());
    }
    let id = required_string(object, "id")?;
    let mode = match object
        .get("mode")
        .and_then(JsonValue::as_str)
        .unwrap_or("host")
    {
        "host" | "host-process" => Mode::Host,
        "docker" | "docker-argv" => Mode::Docker,
        _ => return Err("mode must be host or docker".to_owned()),
    };
    let root = PathBuf::from(
        object
            .get("root")
            .or_else(|| object.get("workspace"))
            .and_then(JsonValue::as_str)
            .ok_or_else(|| "manifest.root is required".to_owned())?,
    );
    let workdir = object
        .get("workdir")
        .or_else(|| object.get("cwd"))
        .and_then(JsonValue::as_str)
        .unwrap_or(".")
        .to_owned();
    let argv = required_strings(object, "argv")?;
    let env = parse_env(object.get("env"))?;
    let image = object
        .get("image")
        .and_then(JsonValue::as_str)
        .map(str::to_owned);
    let timeout_ms = object
        .get("timeout_ms")
        .and_then(JsonValue::as_u64)
        .unwrap_or(DEFAULT_TIMEOUT_MS);
    let outputs = optional_strings(object.get("outputs"))?;
    let manifest = Manifest {
        schema_version,
        id,
        mode,
        root,
        workdir,
        argv,
        env,
        image,
        timeout_ms,
        outputs,
    };
    validate_manifest(&manifest)?;
    Ok(manifest)
}

fn required_string(object: &BTreeMap<String, JsonValue>, key: &str) -> Result<String, String> {
    object
        .get(key)
        .and_then(JsonValue::as_str)
        .map(str::to_owned)
        .ok_or_else(|| format!("manifest.{key} must be a string"))
}

fn required_strings(
    object: &BTreeMap<String, JsonValue>,
    key: &str,
) -> Result<Vec<String>, String> {
    let values = object
        .get(key)
        .and_then(JsonValue::as_array)
        .ok_or_else(|| format!("manifest.{key} must be an array"))?;
    let result = values
        .iter()
        .map(|value| {
            value
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| format!("manifest.{key} entries must be strings"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(result)
}

fn optional_strings(value: Option<&JsonValue>) -> Result<Vec<String>, String> {
    value
        .map(|value| {
            value
                .as_array()
                .ok_or_else(|| "manifest.outputs must be an array".to_owned())?
                .iter()
                .map(|item| {
                    item.as_str()
                        .map(str::to_owned)
                        .ok_or_else(|| "manifest.outputs entries must be strings".to_owned())
                })
                .collect()
        })
        .unwrap_or_else(|| Ok(Vec::new()))
}

fn parse_env(value: Option<&JsonValue>) -> Result<BTreeMap<String, String>, String> {
    let Some(value) = value else {
        return Ok(BTreeMap::new());
    };
    let object = value
        .as_object()
        .ok_or_else(|| "manifest.env must be an object".to_owned())?;
    object
        .iter()
        .map(|(key, value)| {
            let value = value
                .as_str()
                .ok_or_else(|| format!("environment value for {key} must be a string"))?;
            validate_env_entry(key, value)?;
            Ok((key.clone(), value.to_owned()))
        })
        .collect()
}

fn validate_manifest(manifest: &Manifest) -> Result<(), String> {
    if manifest.schema_version != 1 {
        return Err("unsupported manifest schema_version".to_owned());
    }
    if !validate_id(&manifest.id) {
        return Err("manifest.id is not a safe identifier".to_owned());
    }
    if !manifest.root.is_absolute() || has_nul(manifest.root.as_os_str()) {
        return Err("manifest.root must be an absolute path without NUL".to_owned());
    }
    validate_relative_path(&manifest.workdir, "workdir")?;
    if manifest.argv.is_empty() {
        return Err("manifest.argv must not be empty".to_owned());
    }
    for arg in &manifest.argv {
        if arg.is_empty()
            || arg.len() > MAX_ARG_BYTES
            || has_nul_str(arg)
            || arg.chars().any(char::is_control)
        {
            return Err("manifest.argv contains an invalid argument".to_owned());
        }
    }
    for (key, value) in &manifest.env {
        validate_env_entry(key, value)?;
    }
    match manifest.mode {
        Mode::Host if manifest.image.is_some() => {
            return Err("host mode must not specify image".to_owned())
        }
        Mode::Docker => {
            let image = manifest
                .image
                .as_deref()
                .ok_or_else(|| "docker mode requires image".to_owned())?;
            if !validate_docker_image(image) {
                return Err("manifest.image is not a valid Docker image".to_owned());
            }
        }
        Mode::Host => {}
    }
    if !(1..=MAX_TIMEOUT_MS).contains(&manifest.timeout_ms) {
        return Err("timeout_ms must be between 1 and 86400000".to_owned());
    }
    for path in &manifest.outputs {
        validate_relative_path(path, "outputs")?;
    }
    Ok(())
}

fn validate_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn validate_env_entry(key: &str, value: &str) -> Result<(), String> {
    if key.is_empty()
        || key.len() > 256
        || !key.bytes().enumerate().all(|(index, byte)| {
            (index == 0 && (byte.is_ascii_alphabetic() || byte == b'_'))
                || (index > 0 && (byte.is_ascii_alphanumeric() || byte == b'_'))
        })
    {
        return Err(format!("invalid environment key: {key:?}"));
    }
    if value.len() > 32_768 || value.chars().any(char::is_control) || has_nul_str(value) {
        return Err(format!("invalid environment value for {key}"));
    }
    Ok(())
}

fn validate_relative_path(value: &str, field: &str) -> Result<(), String> {
    if value.is_empty() || has_nul_str(value) || Path::new(value).is_absolute() {
        return Err(format!("manifest.{field} must be a relative path"));
    }
    for component in Path::new(value).components() {
        match component {
            Component::Normal(_) | Component::CurDir => {}
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                return Err(format!("manifest.{field} escapes root"))
            }
        }
    }
    Ok(())
}

fn has_nul(path: &std::ffi::OsStr) -> bool {
    path.to_string_lossy().contains('\0')
}

fn has_nul_str(value: &str) -> bool {
    value.contains('\0')
}

fn validate_docker_image(image: &str) -> bool {
    if image.is_empty() || image.len() > 256 || image.chars().any(char::is_control) {
        return false;
    }
    let (without_digest, digest) = match image.split_once("@sha256:") {
        Some((head, digest)) => (head, Some(digest)),
        None => (image, None),
    };
    if without_digest.contains('@') || without_digest.is_empty() {
        return false;
    }
    if let Some(digest) = digest {
        if digest.len() != 64
            || !digest
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        {
            return false;
        }
    }
    let slash = without_digest.rfind('/');
    let colon = without_digest.rfind(':');
    let has_tag = colon.is_some_and(|colon| slash.is_none_or(|slash| colon > slash));
    let (name, tag) = if has_tag {
        let colon = colon.expect("has_tag implies colon");
        (&without_digest[..colon], Some(&without_digest[colon + 1..]))
    } else {
        (without_digest, None)
    };
    if let Some(tag) = tag {
        if tag.is_empty()
            || tag.len() > 128
            || !tag
                .bytes()
                .next()
                .is_some_and(|byte| byte.is_ascii_alphanumeric())
            || !tag
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        {
            return false;
        }
    }
    let (registry, repository) = match name.split_once('/') {
        Some((registry, repository)) => (Some(registry), repository),
        None => (None, name),
    };
    if registry.is_some_and(|registry| !valid_registry(registry)) {
        return false;
    }
    !repository.is_empty()
        && repository
            .bytes()
            .next()
            .is_some_and(|byte| byte.is_ascii_alphanumeric())
        && repository
            .bytes()
            .last()
            .is_some_and(|byte| byte.is_ascii_alphanumeric())
        && repository
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'/'))
}

fn valid_registry(registry: &str) -> bool {
    let (host, port) = match registry.rsplit_once(':') {
        Some((host, port)) if port.bytes().all(|byte| byte.is_ascii_digit()) => (host, Some(port)),
        _ => (registry, None),
    };
    !host.is_empty()
        && host
            .bytes()
            .next()
            .is_some_and(|byte| byte.is_ascii_alphanumeric())
        && host
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.'))
        && port.is_none_or(|port| !port.is_empty() && port.len() <= 5)
}

fn confine_path(root: &Path, relative: &str) -> Result<PathBuf, String> {
    validate_relative_path(relative, "path")?;
    let root = fs::canonicalize(root).map_err(|error| format!("cannot resolve root: {error}"))?;
    if relative == "." {
        return Ok(root);
    }
    let candidate = root.join(relative);
    let parent = candidate
        .parent()
        .ok_or_else(|| "path has no parent".to_owned())?;
    let canonical_parent =
        fs::canonicalize(parent).map_err(|error| format!("cannot resolve path parent: {error}"))?;
    if !canonical_parent.starts_with(&root) {
        return Err("path escapes root".to_owned());
    }
    let target = canonical_parent.join(
        candidate
            .file_name()
            .ok_or_else(|| "path has no filename".to_owned())?,
    );
    if target.exists() {
        let canonical_target =
            fs::canonicalize(&target).map_err(|error| format!("cannot resolve path: {error}"))?;
        if !canonical_target.starts_with(&root) {
            return Err("path escapes root through a symlink".to_owned());
        }
        Ok(canonical_target)
    } else {
        Ok(target)
    }
}

fn canonical_state(manifest: &Manifest, injected: &BTreeMap<String, String>) -> String {
    let mut effective_env = manifest.env.clone();
    effective_env.extend(
        injected
            .iter()
            .map(|(key, value)| (key.clone(), value.clone())),
    );
    let mut out = String::new();
    push_field(&mut out, "schema", &manifest.schema_version.to_string());
    push_field(&mut out, "id", &manifest.id);
    push_field(&mut out, "mode", manifest.mode.as_str());
    push_field(&mut out, "root", &manifest.root.to_string_lossy());
    push_field(&mut out, "workdir", &manifest.workdir);
    push_field(&mut out, "timeout_ms", &manifest.timeout_ms.to_string());
    push_field(&mut out, "image", manifest.image.as_deref().unwrap_or(""));
    for arg in &manifest.argv {
        push_field(&mut out, "argv", arg);
    }
    for (key, value) in effective_env {
        push_field(&mut out, "env.key", &key);
        push_field(&mut out, "env.value", &value);
    }
    for path in &manifest.outputs {
        push_field(&mut out, "output", path);
    }
    out
}

fn push_field(output: &mut String, name: &str, value: &str) {
    output.push_str(name);
    output.push(':');
    output.push_str(&value.len().to_string());
    output.push(':');
    output.push_str(value);
    output.push('\n');
}

fn sha256_hex(input: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(input);
    hash.finish_hex()
}

struct Sha256 {
    state: [u32; 8],
    buffer: [u8; 64],
    buffered: usize,
    length_bits: u64,
}

impl Sha256 {
    fn new() -> Self {
        Self {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
                0x5be0cd19,
            ],
            buffer: [0; 64],
            buffered: 0,
            length_bits: 0,
        }
    }

    fn update(&mut self, mut input: &[u8]) {
        self.length_bits = self.length_bits.wrapping_add((input.len() as u64) * 8);
        while !input.is_empty() {
            let take = (64 - self.buffered).min(input.len());
            self.buffer[self.buffered..self.buffered + take].copy_from_slice(&input[..take]);
            self.buffered += take;
            input = &input[take..];
            if self.buffered == 64 {
                let block = self.buffer;
                self.compress(&block);
                self.buffered = 0;
            }
        }
    }

    fn finish_hex(mut self) -> String {
        let length_bits = self.length_bits;
        self.buffer[self.buffered] = 0x80;
        self.buffered += 1;
        if self.buffered > 56 {
            self.buffer[self.buffered..].fill(0);
            let block = self.buffer;
            self.compress(&block);
            self.buffered = 0;
        }
        self.buffer[self.buffered..56].fill(0);
        self.buffer[56..].copy_from_slice(&length_bits.to_be_bytes());
        let block = self.buffer;
        self.compress(&block);
        self.state
            .iter()
            .map(|word| format!("{word:08x}"))
            .collect::<String>()
    }

    fn compress(&mut self, block: &[u8; 64]) {
        const K: [u32; 64] = [
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
            0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
            0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
            0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
            0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
            0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
            0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
            0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
            0xc67178f2,
        ];
        let mut words = [0u32; 64];
        for (index, chunk) in block.chunks_exact(4).take(16).enumerate() {
            words[index] = u32::from_be_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
        }
        for index in 16..64 {
            let s0 = words[index - 15].rotate_right(7)
                ^ words[index - 15].rotate_right(18)
                ^ (words[index - 15] >> 3);
            let s1 = words[index - 2].rotate_right(17)
                ^ words[index - 2].rotate_right(19)
                ^ (words[index - 2] >> 10);
            words[index] = words[index - 16]
                .wrapping_add(s0)
                .wrapping_add(words[index - 7])
                .wrapping_add(s1);
        }
        let mut working = self.state;
        for index in 0..64 {
            let s1 = working[4].rotate_right(6)
                ^ working[4].rotate_right(11)
                ^ working[4].rotate_right(25);
            let ch = (working[4] & working[5]) ^ ((!working[4]) & working[6]);
            let temp1 = working[7]
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[index])
                .wrapping_add(words[index]);
            let s0 = working[0].rotate_right(2)
                ^ working[0].rotate_right(13)
                ^ working[0].rotate_right(22);
            let maj =
                (working[0] & working[1]) ^ (working[0] & working[2]) ^ (working[1] & working[2]);
            let temp2 = s0.wrapping_add(maj);
            working[7] = working[6];
            working[6] = working[5];
            working[5] = working[4];
            working[4] = working[3].wrapping_add(temp1);
            working[3] = working[2];
            working[2] = working[1];
            working[1] = working[0];
            working[0] = temp1.wrapping_add(temp2);
        }
        for index in 0..8 {
            self.state[index] = self.state[index].wrapping_add(working[index]);
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct CommandResult {
    status: String,
    code: Option<i32>,
    stdout: String,
    stderr: String,
    timed_out: bool,
    duration_ms: u128,
}

impl CommandResult {
    fn to_json(&self) -> JsonValue {
        JsonValue::object([
            (
                "code".to_owned(),
                self.code
                    .map_or(JsonValue::Null, |code| JsonValue::Number(code.to_string())),
            ),
            (
                "duration_ms".to_owned(),
                JsonValue::Number(self.duration_ms.to_string()),
            ),
            ("status".to_owned(), JsonValue::string(&self.status)),
            ("stderr".to_owned(), JsonValue::string(&self.stderr)),
            ("stdout".to_owned(), JsonValue::string(&self.stdout)),
            ("timed_out".to_owned(), JsonValue::Bool(self.timed_out)),
        ])
    }
}

fn run_with_timeout(
    argv: &[String],
    cwd: &Path,
    env_vars: &BTreeMap<String, String>,
    timeout: Duration,
) -> CommandResult {
    let started = Instant::now();
    let mut command = Command::new(&argv[0]);
    command
        .args(&argv[1..])
        .current_dir(cwd)
        .env_clear()
        .envs(env_vars)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            return CommandResult {
                status: "spawn_error".to_owned(),
                code: None,
                stdout: String::new(),
                stderr: error.to_string(),
                timed_out: false,
                duration_ms: started.elapsed().as_millis(),
            }
        }
    };
    let stdout = child.stdout.take().expect("stdout was piped");
    let stderr = child.stderr.take().expect("stderr was piped");
    let stdout_thread = thread::spawn(move || read_capped(stdout));
    let stderr_thread = thread::spawn(move || read_capped(stderr));
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if started.elapsed() >= timeout => {
                let _ = child.kill();
                let _ = child.wait();
                break None;
            }
            Ok(None) => thread::sleep(Duration::from_millis(5)),
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return CommandResult {
                    status: "wait_error".to_owned(),
                    code: None,
                    stdout: join_output(stdout_thread),
                    stderr: format!("{}\n{}", join_output(stderr_thread), error),
                    timed_out: false,
                    duration_ms: started.elapsed().as_millis(),
                };
            }
        }
    };
    let stdout = join_output(stdout_thread);
    let stderr = join_output(stderr_thread);
    let timed_out = status.is_none();
    CommandResult {
        status: if timed_out { "timed_out" } else { "exited" }.to_owned(),
        code: status.and_then(|status| status.code()),
        stdout,
        stderr,
        timed_out,
        duration_ms: started.elapsed().as_millis(),
    }
}

fn read_capped(mut reader: impl Read) -> String {
    let mut bytes = Vec::new();
    let mut buffer = [0u8; 8192];
    while bytes.len() < MAX_OUTPUT_BYTES {
        match reader.read(&mut buffer) {
            Ok(0) => break,
            Ok(count) => {
                let remaining = MAX_OUTPUT_BYTES - bytes.len();
                bytes.extend_from_slice(&buffer[..count.min(remaining)]);
            }
            Err(_) => break,
        }
    }
    String::from_utf8_lossy(&bytes).into_owned()
}

fn join_output(thread: thread::JoinHandle<String>) -> String {
    thread
        .join()
        .unwrap_or_else(|_| "output reader panicked".to_owned())
}

fn docker_argv(manifest: &Manifest, env_vars: &BTreeMap<String, String>) -> Vec<String> {
    let container_workdir = if manifest.workdir == "." {
        "/workspace".to_owned()
    } else {
        format!("/workspace/{}", manifest.workdir)
    };
    let mut argv = vec![
        "docker".to_owned(),
        "run".to_owned(),
        "--rm".to_owned(),
        "--network=none".to_owned(),
        "--read-only".to_owned(),
        "--init".to_owned(),
        "--cap-drop=ALL".to_owned(),
        "--security-opt=no-new-privileges".to_owned(),
        "--pids-limit=256".to_owned(),
        "--mount".to_owned(),
        format!(
            "type=bind,source={},destination=/workspace",
            manifest.root.display()
        ),
        "--workdir".to_owned(),
        container_workdir,
    ];
    for (key, value) in env_vars {
        argv.push("--env".to_owned());
        argv.push(format!("{key}={value}"));
    }
    argv.push(manifest.image.clone().expect("validated Docker image"));
    argv.extend(manifest.argv.iter().cloned());
    argv
}

struct Environment {
    manifest: Manifest,
    root: PathBuf,
    injected: BTreeMap<String, String>,
    digest: String,
}

impl Environment {
    fn effective_env(&self) -> BTreeMap<String, String> {
        let mut env_vars = self.manifest.env.clone();
        env_vars.extend(self.injected.clone());
        env_vars
    }

    fn refresh_attestation(&mut self) -> Result<(), String> {
        self.digest = sha256_hex(canonical_state(&self.manifest, &self.injected).as_bytes());
        write_attestation(&self.root, &self.manifest, &self.digest)
    }

    fn attestation_json(&self) -> JsonValue {
        JsonValue::object([
            ("algorithm".to_owned(), JsonValue::string("sha256")),
            ("digest".to_owned(), JsonValue::string(&self.digest)),
            (
                "path".to_owned(),
                JsonValue::string(self.root.join(ATTESTATION_FILE).to_string_lossy()),
            ),
        ])
    }
}

fn write_attestation(root: &Path, manifest: &Manifest, digest: &str) -> Result<(), String> {
    let path = root.join(ATTESTATION_FILE);
    if fs::symlink_metadata(&path).is_ok_and(|metadata| metadata.file_type().is_symlink()) {
        return Err("attestation path is a symlink".to_owned());
    }
    let value = JsonValue::object([
        ("algorithm".to_owned(), JsonValue::string("sha256")),
        ("digest".to_owned(), JsonValue::string(digest)),
        ("id".to_owned(), JsonValue::string(&manifest.id)),
        ("mode".to_owned(), JsonValue::string(manifest.mode.as_str())),
        (
            "schema_version".to_owned(),
            JsonValue::Number(manifest.schema_version.to_string()),
        ),
    ]);
    fs::write(path, render_json(&value))
        .map_err(|error| format!("cannot write attestation: {error}"))
}

struct Runner {
    environment: Option<Environment>,
}

impl Runner {
    fn new() -> Self {
        Self { environment: None }
    }

    fn handle(&mut self, request: JsonValue) -> JsonValue {
        let object = match request.as_object() {
            Some(object) => object,
            None => return error_json("request must be a JSON object"),
        };
        if let Some(protocol) = object.get("protocol_version") {
            if protocol.as_u64() != Some(PROTOCOL_VERSION) {
                return error_envelope("unsupported_protocol", "protocol_version must be 1");
            }
        }
        let op = match object
            .get("op")
            .or_else(|| object.get("command"))
            .and_then(JsonValue::as_str)
        {
            Some(op) => op,
            None => return error_json("request.op is required"),
        };
        match op {
            "prepare" | "manifest" => self.prepare(object.get("manifest")),
            "inject" => self.inject(object.get("env")),
            "run" => self.run(),
            "collect" => self.collect(),
            "destroy" => self.destroy(),
            _ => error_json("unknown lifecycle command"),
        }
    }

    fn prepare(&mut self, value: Option<&JsonValue>) -> JsonValue {
        if self.environment.is_some() {
            return error_json("an environment is already prepared; destroy it first");
        }
        let value = match value {
            Some(value) => value,
            None => return error_json("prepare requires manifest"),
        };
        let manifest = match parse_manifest(value) {
            Ok(manifest) => manifest,
            Err(error) => return error_json(&error),
        };
        let root = match fs::canonicalize(&manifest.root) {
            Ok(root) if root.is_dir() => root,
            Ok(_) => return error_json("manifest.root is not a directory"),
            Err(error) => return error_json(&format!("manifest.root is unavailable: {error}")),
        };
        if confine_path(&root, &manifest.workdir).is_err() {
            return error_json("manifest.workdir is not confined or does not exist");
        }
        let mut environment = Environment {
            manifest,
            root,
            injected: BTreeMap::new(),
            digest: String::new(),
        };
        if let Err(error) = environment.refresh_attestation() {
            return error_json(&error);
        }
        let response = success_envelope(
            "prepare",
            JsonValue::object([
                ("id".to_owned(), JsonValue::string(&environment.manifest.id)),
                (
                    "mode".to_owned(),
                    JsonValue::string(environment.manifest.mode.as_str()),
                ),
            ]),
            Some(environment.attestation_json()),
        );
        self.environment = Some(environment);
        response
    }

    fn inject(&mut self, value: Option<&JsonValue>) -> JsonValue {
        let Some(environment) = self.environment.as_mut() else {
            return error_json("inject requires a prepared environment");
        };
        let additions = match parse_env(value) {
            Ok(additions) => additions,
            Err(error) => return error_json(&error),
        };
        environment.injected.extend(additions);
        if let Err(error) = environment.refresh_attestation() {
            return error_json(&error);
        }
        success_envelope(
            "inject",
            JsonValue::object([(
                "env_keys".to_owned(),
                JsonValue::Array(environment.injected.keys().map(JsonValue::string).collect()),
            )]),
            Some(environment.attestation_json()),
        )
    }

    fn run(&mut self) -> JsonValue {
        let Some(environment) = self.environment.as_ref() else {
            return error_json("run requires a prepared environment");
        };
        let cwd = match confine_path(&environment.root, &environment.manifest.workdir) {
            Ok(path) if path.is_dir() => path,
            _ => return error_json("workdir is not a confined directory"),
        };
        let env_vars = environment.effective_env();
        let argv = match environment.manifest.mode {
            Mode::Host => environment.manifest.argv.clone(),
            Mode::Docker => docker_argv(&environment.manifest, &env_vars),
        };
        let docker_env = BTreeMap::new();
        let result = run_with_timeout(
            &argv,
            if environment.manifest.mode == Mode::Docker {
                &environment.root
            } else {
                &cwd
            },
            if environment.manifest.mode == Mode::Docker {
                &docker_env
            } else {
                &env_vars
            },
            Duration::from_millis(environment.manifest.timeout_ms),
        );
        success_envelope(
            "run",
            result.to_json(),
            Some(environment.attestation_json()),
        )
    }

    fn collect(&mut self) -> JsonValue {
        let Some(environment) = self.environment.as_ref() else {
            return error_json("collect requires a prepared environment");
        };
        let mut files = Vec::new();
        for relative in &environment.manifest.outputs {
            let path = match confine_path(&environment.root, relative) {
                Ok(path) => path,
                Err(error) => return error_json(&error),
            };
            let metadata = match fs::metadata(&path) {
                Ok(metadata) => JsonValue::object([
                    ("exists".to_owned(), JsonValue::Bool(true)),
                    ("path".to_owned(), JsonValue::string(relative)),
                    (
                        "size".to_owned(),
                        JsonValue::Number(metadata.len().to_string()),
                    ),
                ]),
                Err(_) => JsonValue::object([
                    ("exists".to_owned(), JsonValue::Bool(false)),
                    ("path".to_owned(), JsonValue::string(relative)),
                ]),
            };
            files.push(metadata);
        }
        success_envelope(
            "collect",
            JsonValue::object([("files".to_owned(), JsonValue::Array(files))]),
            Some(environment.attestation_json()),
        )
    }

    fn destroy(&mut self) -> JsonValue {
        let Some(environment) = self.environment.take() else {
            return error_json("destroy requires a prepared environment");
        };
        success_envelope(
            "destroy",
            JsonValue::object([("id".to_owned(), JsonValue::string(&environment.manifest.id))]),
            Some(environment.attestation_json()),
        )
    }
}

fn error_json(message: &str) -> JsonValue {
    error_envelope("invalid_request", message)
}

fn error_envelope(code: &str, message: &str) -> JsonValue {
    JsonValue::object([
        (
            "error".to_owned(),
            JsonValue::object([
                ("code".to_owned(), JsonValue::string(code)),
                ("message".to_owned(), JsonValue::string(message)),
            ]),
        ),
        ("ok".to_owned(), JsonValue::Bool(false)),
        (
            "protocol_version".to_owned(),
            JsonValue::Number(PROTOCOL_VERSION.to_string()),
        ),
    ])
}

fn success_envelope(op: &str, result: JsonValue, attestation: Option<JsonValue>) -> JsonValue {
    let mut response = BTreeMap::from([
        ("ok".to_owned(), JsonValue::Bool(true)),
        ("op".to_owned(), JsonValue::string(op)),
        (
            "protocol_version".to_owned(),
            JsonValue::Number(PROTOCOL_VERSION.to_string()),
        ),
        ("result".to_owned(), result),
    ]);
    if let Some(attestation) = attestation {
        response.insert("attestation".to_owned(), attestation);
    }
    JsonValue::Object(response)
}

fn main() {
    let stdin = io::stdin();
    let mut stdout = io::BufWriter::new(io::stdout());
    let mut runner = Runner::new();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(line) if line.trim().is_empty() => continue,
            Ok(line) => line,
            Err(error) => {
                let _ = writeln!(stdout, "{}", render_json(&error_json(&error.to_string())));
                break;
            }
        };
        let response = match JsonParser::new(&line).parse() {
            Ok(request) => {
                // Echo the request's top-level `id` (if any) into the response so
                // the Python bridge can correlate replies and detect stream desync.
                let req_id = request.as_object().and_then(|obj| obj.get("id")).cloned();
                let mut response = runner.handle(request);
                if let (Some(id), JsonValue::Object(map)) = (req_id, &mut response) {
                    map.insert("id".to_owned(), id);
                }
                response
            }
            Err(error) => error_json(&error),
        };
        if writeln!(stdout, "{}", render_json(&response)).is_err() {
            break;
        }
        let _ = stdout.flush();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_root() -> PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = env::temp_dir().join(format!(
            "evo-env-runner-test-{}-{suffix}",
            std::process::id()
        ));
        fs::create_dir_all(&path).expect("temp root");
        path
    }

    fn manifest(root: &Path) -> Manifest {
        Manifest {
            schema_version: 1,
            id: "test-1".to_owned(),
            mode: Mode::Host,
            root: root.to_path_buf(),
            workdir: ".".to_owned(),
            argv: vec!["printf".to_owned(), "ok".to_owned()],
            env: BTreeMap::from([(String::from("LANG"), String::from("C"))]),
            image: None,
            timeout_ms: 1_000,
            outputs: vec!["result.json".to_owned()],
        }
    }

    #[test]
    fn manifest_validation_checks_argv_env_image_and_paths() {
        let root = temp_root();
        let mut value = manifest(&root);
        assert!(validate_manifest(&value).is_ok());
        value.argv.clear();
        assert!(validate_manifest(&value).is_err());
        value = manifest(&root);
        value.env.insert("BAD-NAME".to_owned(), "x".to_owned());
        assert!(validate_manifest(&value).is_err());
        value = manifest(&root);
        value.mode = Mode::Docker;
        value.image = Some("ubuntu:22.04".to_owned());
        assert!(validate_manifest(&value).is_ok());
        value.image = Some("ubuntu;rm -rf /".to_owned());
        assert!(validate_manifest(&value).is_err());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn digest_is_deterministic_across_env_map_insertion_order() {
        let root = temp_root();
        let mut first = manifest(&root);
        first.env.insert("A".to_owned(), "1".to_owned());
        let mut second = manifest(&root);
        second.env.insert("A".to_owned(), "1".to_owned());
        let first_digest = sha256_hex(canonical_state(&first, &BTreeMap::new()).as_bytes());
        let second_digest = sha256_hex(canonical_state(&second, &BTreeMap::new()).as_bytes());
        assert_eq!(first_digest, second_digest);
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn confined_path_rejects_traversal_and_symlink_escape() {
        let root = temp_root();
        let outside = temp_root();
        assert!(confine_path(&root, "../outside").is_err());
        #[cfg(unix)]
        std::os::unix::fs::symlink(&outside, root.join("link")).expect("symlink");
        #[cfg(unix)]
        assert!(confine_path(&root, "link/secret.txt").is_err());
        let _ = fs::remove_dir_all(root);
        let _ = fs::remove_dir_all(outside);
    }

    #[test]
    fn command_result_json_has_stable_semantic_fields() {
        let root = temp_root();
        let result = run_with_timeout(
            &["printf".to_owned(), "hello".to_owned()],
            &root,
            &BTreeMap::new(),
            Duration::from_secs(2),
        );
        let json = render_json(&result.to_json());
        assert!(json.contains("\"status\":\"exited\""), "{json}");
        assert!(json.contains("\"code\":0"), "{json}");
        assert!(json.contains("\"stdout\":\"hello\""), "{json}");
        assert!(json.contains("\"timed_out\":false"), "{json}");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn docker_argv_disables_network_by_default() {
        let root = temp_root();
        let mut value = manifest(&root);
        value.mode = Mode::Docker;
        value.image = Some("ubuntu:22.04".to_owned());
        let argv = docker_argv(&value, &value.env);
        assert!(argv.contains(&"--network=none".to_owned()));
        assert!(argv.contains(&"--cap-drop=ALL".to_owned()));
        assert_eq!(argv[0], "docker");
        let _ = fs::remove_dir_all(root);
    }
}
