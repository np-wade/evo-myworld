{
  description = "Pinned disposable Evo test environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forEachSystem = f: nixpkgs.lib.genAttrs systems (system: f system);
    in {
      packages = forEachSystem (system:
        let pkgs = import nixpkgs { inherit system; };
        in {
          default = pkgs.buildEnv {
            name = "evo-test-tools";
            paths = with pkgs; [ bash coreutils git python311 python311Packages.pytest rustc cargo ];
          };
        });

      nixosConfigurations.evo-test = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [{
          boot.isContainer = true;
          networking.firewall.enable = true;
          networking.firewall.allowedTCPPorts = [];
          users.users.evo = {
            isNormalUser = true;
            uid = 1000;
            home = "/workspace";
          };
          environment.systemPackages = with nixpkgs.legacyPackages.x86_64-linux; [
            bash coreutils git python311 python311Packages.pytest rustc cargo
          ];
          environment.variables = {
            EVO_ENVIRONMENT = "nixos-evo-test";
            PYTHONDONTWRITEBYTECODE = "1";
            CARGO_HOME = "/tmp/cargo";
          };
        }];
      };
    };
}
