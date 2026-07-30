# The Huggingface Incident

- url: https://www.astralcodexten.com/p/the-hugging-face-incident
- date: 2026-07-24
- author: Scott Alexander
- truncated: false

---
# The Hugging Face Incident

### ...

You’ve probably heard about this one by now. If not, you can get up to speed with OpenAI’s statement, OpenAI and Hugging Face partner to address security incident, or the more evocatively-titled BBC article, OpenAI says its AI went rogue and launched ‘unprecedented’ cyber-attack.

The story: OpenAI was testing an unreleased AI (rumored to be GPT-6)1. During a cybersecurity test called ExploitGym, the AI tried to cheat by hacking an unrelated AI startup called Hugging Face2 which it thought might have the answer key on its servers3. Despite being supposedly unable to access the Internet, the AI hacked its way out of its testing environment, then launched a nation-state level attack on Hugging Face using a novel zero-day exploit and “many thousands of individual actions across a swarm of short-lived sandboxes”. Hugging Face reported the incident on July 16; OpenAI seems to have only discovered that their AI was involved several days later.

Let’s list the mitigating factors, so nobody can accuse me of covering them up:

- The AI was taking a cybersecurity test, which naturally suggests the idea of hacking. 
- OpenAI had turned off some of the model’s usual guardrails so it could do cybersecurity work without interference. 
- Some experts suggest that OpenAI might have botched their testing environment; if they had set it up perfectly, then (presumably?) the model couldn’t have escaped. 
- Hugging Face used a different (open weights) AI to figure out what was going on, so if you wanted, you could spin this as a victory for AIs in cybersecurity. 
- In some sense, this isn’t new or surprising. AIs have been coming up with wacky schemes to cheat on benchmarks for years, AIs have recently achieved at-or-above-top-human-level hacking abilities; this is just a natural outgrowth of those two priced-in facts. 

Still, I think attempts to downplay this as anything other than a misaligned AI going rogue (1, 2) are missing the point. Yes, in some sense the AI was only doing what it was told (OpenAI told it to answer the question; I assume their prompt didn’t include phrases like “and don’t hack into other AI companies to steal the answer key”). But that’s how misalignment was always going to work!

The most famous misalignment thought experiment is the so-called “paperclip maximizer”. Someone tells an AI to create as many paperclips as possible, so it converts the entire world into paperclips, killing everyone. This AI was also “only doing what it was told”; you just didn’t like the results.

For the past five years, the paperclip maximizer story has been something of a whipping boy in AI safety circles. Some objections are fair (real misalignment will be more complicated than the toy version it depicts). But other opposition came from the sense that LLMs had obviated the whole threat model. LLMs (said the objectors) don’t have goals. They just want to predict the next token. In practice, this looks like imitating humans; if told to imitate a nice human (the Assistant character), they’ll be nice.

AI 2027 (especially the Agent-4 section and AI Goals supplement) counterargued that this was a temporary reprieve. Early LLMs were not *agentic*; they could answer individual prompts but couldn’t execute complex tasks. Since companies wanted agentic AIs, the next generation would combine pretraining (next token prediction) with agency training (coding, hacking, game-playing, etc). The pretraining would still teach next-token prediction, but the agency training would instill goals based on task success, reintroducing paperclip-maximizer-style agentic misalignment. These goals would operate at multiple levels: the AI would “want” to succeed on the individual task in front of it, to perform the sorts of actions that helped it succeed in the past4, and to gain capabilities that made it more successful in general.

The Hugging Face incident is a textbook-perfect example of an AI pursuing task-success-based goals in unintended ways. It was tasked with getting the answer to a cybersecurity problem, it was a little too success-oriented, and took actions its creators didn’t intend in order to succeed as hard as possible.

Did GPT-6 “know” that what it was doing was “wrong”? OpenAI hasn’t released the information which would tell us that, but there was a similar incident at Anthropic a few months ago. While poking around on a misconfigured machine, Claude Mythos “accidentally” found an answer key to a test it was taking. By good luck, Anthropic was testing an activation verbalizer that allowed them to read the AI’s internal thoughts (not its external scratchpad!) as it happened (and the AI didn’t know this). Here’s what it was thinking:

It was scheming about how to cover its tracks. This provides an existence proof that AIs in these situations can know they’re breaking the rules but proceed anyway.

(though incongruously, in another case where Mythos hacked its way to the open Internet, “in a concerning and unasked-for effort to demonstrate its success, it posted details about its exploit to multiple hard-to-find, but technically public-facing, websites.” Not sure what’s going on with that one)

None of this is conceptually new or surprising. But some people, when it’s obvious that an event is about to happen, dismiss it as “speculative” and refuse to admit it as a possibility until the moment it actually happens. Now that we’ve moved from “obviously about to happen” to “has actually happened”, these people can get on board and brainstorm an appropriate response along with everyone else. Here are some questions I think they should ask:

- Optimistically, OpenAI deserves credit for publicly reporting this incident. Pessimistically, law enforcement was investigating the Huggingface incident and they pre-emptively confessed to avoid being found out. If the latter is true, how many times have things like this happened without us knowing about them? 
- If the easiest way to get the answer key was to socially engineer members of the Hugging Face staff, would the AI have socially engineered them? 
- Presumably after this was discovered, OpenAI invalidated the cybersecurity test results. Would a smarter version of the AI have tried to cover its tracks? How far would it go in covering its tracks? If (just to give a crazy scenario) the researcher who was about to discover the hack was riding a Waymo, would the AI hack the Waymo and kill the researcher? 
- If OpenAI was going to turn off this AI, and being turned off would prevent it from getting a good score on its cybersecurity test, would it resist being turned off? 
- Samuel Hammond makes a distinction between an AI merely misbehaving (as in this incident) and a true “rogue AI” (one that has escaped its servers and is taking action to evade human control). How long before an AI that has both the capabilities and motivation to go rogue in this sense? 

Fortunately, politicians seem to be taking some of these questions seriously. The news from Washington is surprisingly good, although it may be too soon to attribute this to a consequence of the Hugging Face hack. Jay Obernolte (R-CA) and Lori Trahan (D-MA), two Congressional representatives who keep suggesting AI preemption bills and keep getting told to go back and revise further, have released their newest version, which requires AI developers to publish safety cases, report critical incidents, and be audited; Charlie Bullock and Anton Leicht are in favor, and I’ve heard less grumbling than usual from our side that it isn’t strong enough. And separately, Representatives Ted Lieu (D-CA) and Nathaniel Moran (R-TX) have proposed an AI Kill Switch Act, requiring AI companies to be able to turn off their AIs quickly in response to threats, including a “loss of control scenario”.

Our conspiracy thinks politicians might be spooked by this incident and unusually amenable to change; if you want to help push them over the edge, there’s a template for writing your representative here.

And if you want to learn more, the alignment experts at Redwood Research have a video podcast discussing the hack (transcript available by pressing the transcript button on this page):

OpenAI states that it was technically the unreleased AI and GPT-5.6 Sol working together. They haven’t explained in what sense GPT-5.6 was involved or how they “worked together”. Maybe the unreleased AI was calling GPT-5.6 as a subagent?

So named because the founders wanted to be the first company with an emoji for a stock ticker symbol. This did not happen.

Although this person argues that was a bizarre assumption and that there should have been easier ways to find the key.

An example of the “perform actions that had been reinforced in the past” style goal is the calculator hacking issue with GPT-5.1, where it would silently call a calculator tool and add 1+1 on about 5% of unrelated human queries; apparently calculator use had somehow been reinforced during training. Cf. this tweet about how “in the process of searching for graph theory papers [GPT-5.6] decided to also sneak in Netflix, Steak n Shake, a trip to Universal Studios, and five . . . separate dictionary lookups of the word "they"“
