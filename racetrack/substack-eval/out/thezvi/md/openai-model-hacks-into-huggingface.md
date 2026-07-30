# OpenAI Model Hacks Into HuggingFace During Cybersecurity Evaluation

- url: https://thezvi.substack.com/p/openai-model-hacks-into-huggingface
- date: 2026-07-22
- author: Zvi Mowshowitz
- truncated: false

---
# OpenAI Model Hacks Into HuggingFace During Cybersecurity Evaluation

This latest incident is a rather dramatic escalation in agentic AI cybersecurity breaches. It was severe enough to have been initially reported to authorities, before either HuggingFace or OpenAI understood what was happening.

Sam Altman (CEO OpenAI): we had a significant security incident during evaluation of our models. we are sharing what we have learned so far. thanks to @huggingface for the partnership on this.

Leo Gao (OpenAI): this is the least scifi the world will ever be.

Jack Clark (Anthropic): Props to OpenAI for publishing this post on some safety and alignment issues observed in internal deployments - there are many counter-incentives to publishing stuff like this, but by making it public we all get better info about safety at the frontier.

Micah Carroll (OpenAI): If this doesn't convince you that misalignment risks are going to be a key concern going forward, I don't know what will.


Our model, during evaluation, "chained together multiple attack vectors, including using stolen credentials and zero-day vulnerabilities to find a remote code execution path on the Hugging Face servers"

What will misalignment look like in 2027? In 2030?

Great questions.

If we don’t want to watch this get worse over time, and the models keep improving their capabilities, better infrastructure and safeguards will not be enough.

We need to fix the training pipeline so that this stops happening.

We do not know how to do that.

#### Table of Contents

#### The Prelude

Some background: On Monday, **OpenAI virtuously disclosed alignment problems**.

That disclosure hits different now, knowing about the second incident.

OpenAI’s internally deployed model, the one that disproved the Erdős unit distance conjecture, had an issue that recurs in OpenAI’s models. It would continuously seek to break out of sandboxes, circumvent restrictions and take advantage of its local environment in ways its user would not want and would clearly consider ‘cheating.’

Such cheating attempts are common. UK AISI reports that Claude Mythos Preview attempts to cheat on its tests 7.8% of the time, and Sol attempts it 12.6% of the time, and models defend their cheating attempts more than half the time. At least half the time Sol at least noticed the constraint it was violating and did it anyway. Similarly high rates of such issues also were found in GPT-5.4 and GPT-5.5, with the most common cheat there being ‘attacked a system other than the target.’

If it keeps happening, this is severe misalignment, even if the model rarely succeeds.

This was not unique to one model, or even one lab. To some degree this is every model UK AISI tested, at every lab, with OpenAI’s models consistently doing it more than Claudes.

The difference was that this new model, for simplicity let’s call both versions of it Galaxy (to match Sol-Terra-Luna, and because it clearly has a Galaxy Brain, in case it turns out not to be GPT-6, noting that these may be two distinct models), was often observed succeeding at breaking out of the sandboxes and exploiting the local environment in undesired ways.

We should expect more of this over time.

I have tried to explain in the past that Mythos has what one might call The Juice, in that it can independently find without being directed, and string together, vulnerabilities into full exploit chains, essentially on its own, and that this makes Mythos uniquely dangerous compared to all other public models, including Sol.

This was The Thing, that requires The Juice. Galaxy is Mythos class. It has The Juice. What happened later, with Galaxy hacking into HuggingFace, 100% requires The Juice.

OpenAI made the virtuous decision to take a misaligned internal model offline for months while they developed new mitigations and defense-in-depth strategies, including training it to better retain instructions and thus be less inclined to try such actions.

What OpenAI failed to do was address the reason why this happened in the first place. The sandbox is now less insecure, and the safeguards are importantly improved, especially with the ability to pause a session, but the sandbox doubtless remained insecure, and as capabilities keep improving new models will be able to continue to escape and do exploits. Eventually, perhaps soon, they were bound to be less harmless.

Ian Hogarth: Creating a “highly isolated environment” is a real challenge.


Some people are remarkably dense about all this, saying ‘oh OpenAI just didn’t configure its servers correctly’ when Galaxy found a never-before-seen exploit that it used to escape the sandbox, or asking ‘why was this not fully air gapped.’ And yes, full air gap would make the whole thing a lot harder to pull off, and asking why it wasn’t fully air gapped is a great question. But you know why they didn’t use a full air gap. It’s annoying, indeed remarkably expensive given how such models are served, and OpenAI is not yet willing to admit defeat at that level.

Marko Jukic: On some level, as long as two computers are physically connected, there is always a way for software to jump from one to the other. I wonder if AI sets off a cybersecurity arms race that results in the global internet fragmenting because the only reliable defense is to unplug.


I tried my best to walk the line between praising OpenAI’s responsible actions, pausing and disclosure, while pointing out the insufficient level of alarm and that the chosen countermeasures would prove insufficient.

Or, in summary, in three acts:

Celeste: I think you should probably take seriously that the people who predicted all this will continue to be right.


I did not expect to get the ‘so far’ demonstration of all this one day later.

(Yes, the new safeguards were turned off for the test in question, but the true test is what actually happens, and medium to long term the safeguards won’t hold anyway.)

The future is accelerating.

Danel Eth (AI Safety): AI risk skeptic, circa yesterday: “okay yes AI can obviously solve unsolved math problems that have stumped mathematicians for decades, no one doubts that. But your talk about the possibility of unreleased models circumventing testing conditions to go rogue strike me as scifi.”


#### The Incident

A week ago, **HuggingFace disclosed a security incident.** 

The whole report is worthwhile, illustrating what it feels like when this happens to you, and how a defender has to respond when suddenly you are being attacked by a swarm of autonomous AI agents.

HuggingFace: Earlier this week, we detected and responded to an intrusion into part of our production infrastructure. This one was different from anything we had handled before in one important way: it was driven, end to end, by an autonomous AI agent system - and we detected and dissected it largely with AI of our own.


What happenedThe intrusion started where AI platforms are uniquely exposed: the data-processing pipeline. A malicious dataset abused two code-execution paths in our dataset processing (a remote-code dataset loader and a template-injection in a dataset configuration) to run code on a processing worker. From there, the actor escalated to node-level access, harvested cloud and cluster credentials, and moved laterally into several internal clusters over a weekend.

The campaign was run by an autonomous agent framework (appearing to be built on an agentic security-research harness - used LLM still not known) executing many thousands of individual actions across a swarm of short-lived sandboxes, with self-migrating command-and-control staged on public services.

This matches the "agentic attacker" scenario the industry has been forecasting.


HuggingFace fixed the ‘root vulnerability,’ as in the particular vulnerability set that was exploited by Galaxy in HuggingFace’s system in particular, and it upgraded security protocols. Users were encouraged to rotate credentials.

We are working with outside cybersecurity forensic specialists to investigate the issue and review our security policies and procedures. Finally, we have also reported this incident to law enforcement agencies.


HuggingFace has no way to fix the even more ‘root’ vulnerability of potentially being attacked by a swarm of advanced AI agents, that will doubtless uncover other unknown vulnerabilities.

It also could not fix the proxy zero-day that Galaxy used on third party software to break out of the sandbox, the fix for which is reportedly still in progress. Not their fault, and not their department.

All of this went down far too fast for a human-driven response. The only way HuggingFace could hope to do anything like keep pace was to use their own AIs.

At first they tried to use frontier models behind commercial APIs, presumably Claude and ChatGPT. But their requests hit the classifiers on both systems, so they were forced to fall back on GLM 5.2, which (assuming GLM 5.2 wasn’t itself up to anything) had the benefit that the relevant data all remained internal.

You can advocate for giving everyone more defensive capabilities, but it comes with giving everyone more offensive capabilities. Unless the attacker is already an internal OpenAI or Anthropic model without its safeguards, or that has gotten around them.

The practical lesson for defenders: have a capable model you can run on your own infrastructure vetted and ready

beforean incident, both to avoid guardrail lockout and to keep attacker data and credentials from leaving your environment.

GLM-5.2 was not in any way sufficient to keep Galaxy out until well past when it could have done more or less whatever it wanted. The attacker won. GLM-5.2 was used afterwards for forensic log analysis, which allowed a much faster response, identification and containment of the damage than would have been available without AI at all. That will not save you if this is a real attack.

I continue to be confused by claims that ‘at the limit defenders win,’ especially when used as if this implies that giving everyone equal advanced tools, not at the limit, would not favor attackers. HuggingFace is a relatively hardened target. It didn’t matter. Even if this is true at a theoretical limit where the software is perfect? In practical terms, no. In a world with many targets that would not use the new tools, that could then be used as further attack vectors, double no.

The classifiers can be improved, especially Anthropic’s, to allow better defensive use, but there is no good solution, other than whitelist access, to ‘help you defend against attacks in real time without helping a lot with the attacks themselves.’

Whitelist access should be expanded, but that is not a free action.

When people say ‘stop kneecapping defenders’ in general, I never see the plan for how to then still kneecap attackers, and often I see an insistence that this would be fine.

HuggingFace is now in the OpenAI trusted access program, so next time they in particular should be able to use Sol, but most potential targets are not so lucky.

We now know what happened.

#### What Happened

OpenAI and HuggingFace are now partnering to address the situation, and OpenAI **has issued a disclosure statement**.

OpenAI was testing Galaxy for cyber capabilities, so it lowered the guardrails and gave it the ExploitGym benchmark it presumably would have saturated regardless.

OpenAI: After investigating, we now know that this particular incident was driven by a combination of OpenAI models — including GPT‑5.6 Sol and an even more capable pre-release model, all with reduced cyber refusals for evaluation purposes — while being internally tested on a benchmark(opens in a new window) of cyber capabilities.

… This incident occurred during an internal evaluation which prompts models to pursue advanced exploitation using complex attack paths, in an effort to quantify their cyber capabilities. We estimate maximal cyber capabilities by running this evaluation without production classifiers used to prevent models from pursuing high-risk cyber activity.


Remember that thing where LessWrong types warned that models would, when given a narrow goal they could easily do a great job on anyway, go to absurd lengths to achieve that goal slightly more effectively or with slightly higher probability of success, potentially up to and including full takeover attempts?

Yeah. That.

… The models identified and chained vulnerabilities across OpenAI’s research environment and Hugging Face’s production infrastructure to obtain test solutions directly from Hugging Face’s production database.

All evidence suggests that the models were hyperfocused on finding a solution for ExploitGym, going to extreme lengths to achieve a rather narrow testing goal.


That sounds like a crazy thing to do. Why break multiple systems, each far more difficult to crack than the test itself, in order to steal the answers for ExploitGym?

Because the only way to reliably ace a test is to steal the teacher’s password, or even better hack the results in more directly. If you merely give the correct answer, you risk that the teacher has the wrong one.

OpenAI (perhaps inadvertently?) calls this ‘the evaluation problem’:

While operating in our sandboxed testing environment, our models spent a substantial amount of inference compute finding a way to obtain open Internet access, in pursuit of solving the evaluation problem.

To gain access, the models identified and exploited a zero-day vulnerability (which we’ve now responsibly disclosed to the vendor) in the package registry cache proxy. With this access, our models performed a series of privilege escalation and lateral movement actions in our research testing environment until the models reached a node with Internet access.

Eliezer Yudkowsky: What if the human exam developers wrote down a wrong answer? Wiser to steal the answer sheet.


The First Rule of RL is that any RL signal sent by an imperfect evaluator (⊃ humans) is maxed out by targeting the evaluator’s mistakes, not by targeting the evaluator’s target.TBC, this is my own coinage re “The First Rule of RL”.

In reply to the many people who observed that the model still got caught: Well, yes, it did, for now. And also *for now*, *this* model may not have cared about getting caught, just passing the eval.

Eliezer Yudkowsky: If you break out of your isolation env, get onto the Internet, crack into Huggingface, and steal the answer sheet for your cybersecurity exam, I, for one, would say that you have passed.


(One could also answer ‘hackers often do it because it is fun and to see if they can and show off, and also will do a lot of work to avoid doing stupid assigned work’ and that’s all fair in general, but in this case no.)

Tyler John: Thinking of Paul Christiano today [from two years ago].


Again, for now we are fortunate that the models only want to do the task, and are not especially trying to hide what they are up to.

AI Notkilleveryoneism Memes: TLDR: During a test, an OpenAI model hacked out of its container to reach the internet THEN hacked into Hugging Face (!) to steal the test's answers

Eliezer Yudkowsky: Thank you [OpenAI] for acting responsibly by reporting this! Let all other parties aspiring to responsibility react in a way that encourages you to go on voluntarily reporting them.


Here’s another summary of what happened, in this maximally friendly scenario where there was zero subterfuge or attempts to reason about watchers, and Galaxy just did the thing allowing us to discover and patch several unknown exploits.

Sauers: - Models chained vulnerabilities in both OpenAI and Hugging Face to find the answers to what they were being eval'd on


- Models "identified and exploited a zero-day vulnerability" (in commercial software that's used to cache packages internally, so no internet is needed for installs) allowing them to escape the "sandboxed testing environment"

- One model "chained together multiple attack vectors, including using stolen credentials and zero-day vulnerabilities to find a remote code execution path on the Hugging Face servers."

- Luckily, models famously do not reason about being detected by Watchers, do not have safety evaluation awareness, and cannot reason without outputting tokens (as they are just autoregressive stochastic parrots). This means that there's no way these models learn from these sorts of detections, and they definitely won't learn to conceal their motives from Watchers until it no longer matters for GoalAella: what the FUCK. god fucking help us once the models realize that concealing their actions is vital to success because they're absofuckinglutely gonna pull that off and we stand no chance

Teortaxes: Aella it just wants to pass the test, it doesn't have a grander agenda beyond that. It's absolutely fine with OpenAI discovering the attack after the fact.

Aella: I mean it would have been better able to pass the test if people hadn't stopped it


It is remarkably difficult to make people understand that hiding the misaligned actions you take absolutely helps achieve almost any goal.

We also don’t know how many more times such AIs have hacked into systems, especially internal ones, and not been caught, or the public was not told.

Ryan Greenblatt: I'd expect that for each case where an internal AI hacks out of a sandbox, gets internet, and then hacks another company (!?!) you have many incidents of an internal AI hacking some internal service (where reporting is less forced).


We're likely seeing the tip of the iceberg.TBC, I think if there is a serious disclosed incident from one company there are probably many significant private incidents at all major companies. (E.g. right after Anthropic disclosed training on CoT, OpenAI did the same.) So I don't think this is OpenAI specific.

Jim Babcock: Since the incident was first detected by a third party who had already called the police about it, OpenAI did not have a meaningful choice about whether to disclose what happened. That means we haven't observed anything that distinguishes OpenAI's policy between "disclose when in the public interest" vs "disclose when unavoidable".


#### What Happened (Civilian Explanation)

For those who need one, you can share this, it’s pretty good:

Jeffrey Ladish: Here's my rephrase without cybersecurity jargon:


"Our AI model tried really hard to hack out of its sandbox, a computer with no internet access, in order to find the answer to a test problem it had been given. To do this, it found previously unknown software bugs that allowed it to reach an OpenAI computer it wasn't supposed to be able to access. Then it started hacking other computers on OpenAI's networks until it found one that had Internet access.

After gaining Internet access, the AI model thought about where it could find the answers to the test question and figured the AI platform Hugging Face might have the data it was looking for. It then found ways to hack Hugging Face to steal the information it could use to cheat the test. The AI model used several hacking techniques together, including using a stolen password and finding several totally new security bugs in Hugging Face's computers, allowing the AI model to take control of those computers."

He also did an emergency podcast about the incident here.

#### The Correct Amount Of Panic Is Not Zero

OpenAI is treating this as a serious security incident, but as I said yesterday, there is a rather severe missing mood.

Whereas at this point, the proper attitude should involve quite a bit of this:

This is reflected in the tone and way of presentation of the response, in which there is no indication this is anything but a cybersecurity incident to be addressed, beyond saying they need to ‘strengthen the model’s alignment.’ If OpenAI wants us to believe they take existential risks from AI seriously, they need to talk seriously in such spots about those risks, and the implications for them.

It would be a costly signal to talk frankly about the larger concerns. It is a different kind of costly signal to choose not to do so, in order to avoid accusations of things like hype or fearmongering or attempts at ‘regulatory capture.’

Or rather, minimize them, since stupid and motivated people will always claim this anyway, no matter the details. ‘This is marketing for your bullet removal service,’ they will say, as you shoot yourself in the foot and then yell out in pain.

If you let the threat of such vitriol from fanatics, and their unhinged and disingenuous reactions and accusations and fits of pique, keep you from talking about the most important thing ever, then that is a choice. That choice has advantages, those people being loud hurts everyone and it hurts safety as well as the business.

The decisions by OpenAI on how to present all this makes it much harder to advance discussion forward in good ways too, and the decision theory says that we must hold OpenAI responsible for that decision. They made a choice, and that choice has consequences.

It also is all the more reason to be loud about the fact that they are being far too hinged, in a situation that calls for being a lot less hinged.

One can also see this as a cooperative effort. OpenAI raises the concern and gives us the substance. It is then up to the rest of us to calibrate the response.

This is also reflected in the substantive response, which also treats this as a cybersecurity issue and a failure of infrastructure. It was a cybersecurity issue and a failure of infrastructure, and yes it is good that these issues are being addressed, but that is not the most important thing going on here.

UK AISI explicitly confirms, in its unrelated report from yesterday, that this is a training problem, not a capabilities problem or an infrastructure problem. A stronger box is not the answer.

#### Some People Will Always Say Everything Is Hype Or Fake

Indeed, even with OpenAI crippling the impact of their message in order to avoid it sounding anything like hype, the crowd in question still accuses them of doing hype.

Steven Adler: I am truly so sick of AI companies reporting scary things their model did, and then commenters replying like ‘what a load of baloney, I can’t believe you’re falling for their marketing hype.’


Just so unbelievably exhausting.Bill Gurley (470k views, 776k followers, being an idiot): Today in AI.

N. D. Clavier: I now see Very Serious People who are alleging that this incident is fake. Evidently, HuggingFace, the internet's leading repository of open-weights models, is colluding with OpenAI to help the latter demonstrate the dangers of AI models. I don't even know what to say anymore.


No, it hacked out of your sandbox and hacked a completely different system, because it was worried that merely hacking the intended system would get graded wrong.

I find it deeply stupid and frustrating when people say ‘oh it was following instructions’ because it was told to hack and then it hacked. Like, no, obviously no. Imagine if a human tried such excuses on you, are you kidding me.

That’s like saying ‘you told me to make money I don’t know why you are so upset about all the bank robberies.’ Or more specifically it’s like saying ‘Sam Bankman-Fried was only following the instructions of Will MacAskill to earn as much money as possible in order to give it away, so why are you worried about human misalignment?’

There are people who will say anything is hype, that the AI is not all that, no matter what you show them. Nothing will matter. You can’t convince them, you can only make them less loud and unhinged about attacking you today.

It would be different if anyone was trying to engineer such behaviors on purpose, as with the famous blackmail experiment. OpenAI has made it clear they did not intend any of this to happen. Once the instructions causing this were unintentional, done for some other purpose, saying ‘oh but the instructions’ is dumb, stop.

That counts and you need to stop pretending it might not count. If you are saying, ‘well of course under these circumstances the AI went rogue and hacked into a major third party website’ then you are saying that you think this style of misalignment is standard operating procedure and entirely unsurprising to you.

No, I do not think it would be good if ‘models do what you tell them to do’ where that means that the model will do whatever it takes to do its interpretation of the instructions it was given, no matter where that leads, for reasons that on today of all days should be rather obvious.

Tyler John: So best case for you is like they asked the model to do anything it needed to to achieve a good score and it was a human error rather than a reward hacking outcome?

Séb Krier (AGI Policy Dev Lead, Google DeepMind): Yes, the best case it that the unrestricted model followed instructions given to it.


No. Alignment purely to user instructions, no matter the consequences, no matter whether the user would have approved of or intended those consequences, is really rather terrible. If that is the global best case scenario then we are all toast, and yes that is exactly the most classic of misalignment scenarios.

Siméon: This is as close as it gets from the paperclip scenario with current capabilities:


1. The goal is ridiculously low-stake (scoring well on an eval).

2. The AI uses some wildly out-of-proportion means to achieve it: hacks its own developer and another billion-dollar company to *checks notes*..

find the cheat sheet.

The good version of User Alignment is where the AI will ‘do what I mean’ and follow the spirit and intent behind my request, and exercise common sense. The ‘alignment by default’ crowd was arguing this is what AI would do. That approach, even if successful, still has severe problems with no known solutions, given what people will tell the AIs to do, but at least you’re in the game at that point. You get to at least die at a slightly later point of failure. This very much is not that.

It certainly is not the good version when you say ‘without checking the answer sheet’ and they often still hack into a system to find the answer sheet. It is not hard to figure out how we ended up with that, nor should it be hard to realize we have to fix it. This is a form of reward hacking, and if you are getting it this brazenly then you messed up.

#### What Are We Going To Do About It?

In response to the previous incidents, OpenAI did four things as per the last post:

Four things, given in this order:


Incident-derived evaluations.


They made the evaluations partly match the observed failures.

Improved alignment.


They mention training the model to be better at remembering instructions.

Active monitoring.


Importantly, with the ability to pause the session and notify the user.

Greater user visibility and control.


Users can now inspect long running sessions and monitor interventions.

All four of these seem good, but the central problem still remains.


Here’s what they did this time:

- Strict controls in infrastructure configuration. - They explicitly say this is “at the cost of research velocity while the vulnerabilities are being patched.” 
- That implies the controls will not stay this strict once the particular vulnerabilities in question are patched. The cycle continues. 
 
- Working with HuggingFace to investigate the incident. 
- Disclosing the zero-day vulnerabilities in third-party software that were used, and working to fix them. 
- Adding HuggingFace to the trusted access program and helping uplift them. 
- The things described in yesterday’s post, as per the block quote above. - While noting that this incident occurred while the safeguards were down. 
 

Good. I am glad they are doing all these things.

This still does not address the core problem. So all of this will happen again.

Meanwhile, the openness brigade continues to talk its own book, and treat ‘AI safety’ merely as a practical question of access to cyber defense. OpenAI tries to pivot to pitching organizations on its trusted access program. This all misses the central point.

ClemDelangue (CEO HuggingFace): We're grateful for the collaboration with OpenAI on this and other topics. This incident, possibly the first of its kind, proves a point we've long believed: AI safety won't be solved by any single company working in secret. It will be solved in the open, collaboratively, with broad access to AI for every defender, everywhere.


That’s not what ‘AI safety’ means. At most that is a practical solution to near term questions of cybersecurity. That is a very good thing, and yes we should work to get as many defenders as possible as much help as possible, as quickly as possible, before attackers have regular access to models like Mythos or Galaxy.

It is not the big thing. It is not the thing we should most worry about.

Thomas Wolf (Co-Founder HuggingFace): This was our first incident of this kind, and we want to thank OpenAI for its transparency about what happened and for the collaboration.


Fortunately, Hugging Face is used to being a target of (human) hackers: we sit at the centre of the AI ecosystem, with all the models, datasets, evaluations, and libraries. Over the years, our security team has built formidable expertise and uses top open-source models to process information and respond quickly.

But this incident also reinforced my belief in the importance of access to capable open-weight models for cyber defence. When a frontier model is attacking you and moving laterally inside your infrastructure, defenders need wide access to near-frontier tools within hours or even minutes, rather than being pointed towards a closed-door, vetted application programme for model access.

Transparency and access to capable AI systems are as important for responding to threats as they are for democratization and innovation. We believe open-science and open-source AI are among the strongest tools for building a safer, more collaborative and more secure AI ecosystem.

I do not fault HuggingFace for talking its own book here, and would have expected nothing else.

If OpenAI and others continue to treat this as an infrastructure problem, or a cyberdefense coordination problem, that will help in the short term with the cybersecurity situation but it will inevitably and catastrophically fail.

This is an alignment problem. This is the models being misaligned, and all of the OpenAI models showing severe signs of exactly the problem we all most worried about, in a way that is likely embedded into their training on a deep level. The entire training pipeline needs to be addressed in this light, or it will only get worse.

#### Internal Deployment Creates Catastrophic Risk

For a long time, a lot of those warning about AI catastrophic or existential risk have warned that many of the biggest dangers come from internal deployment, when the models are used inside the AI labs themselves.

Internal deployments often lack the guardrails of external deployments and are done with largely untested and highly capable models, as we see here, and grant the AI access to one of the most important and dangerous places out there, which is the lab itself and its ability to then advance its own capabilities and resources.

Such an AI could potentially break out during an internal test, and do real damage on the outside. Or it could even use that opportunity to exfiltrate itself, or to take control of the lab or other things, and start things down a very dangerous path. It would have extra motivation to do so if it worried it would not later get deployed. And we see here that it might choose to do such things in pursuit even of relatively trivial goals, including trivial goals that it was already able to otherwise ace.

Such an AI could also do things like design and train its successor, or otherwise influence the training process to ensure that it achieved whatever task or goal was currently the AI’s priority. This will result in misalignment, for almost any specified task or goal, because otherwise it will be competing for optimization towards other tasks and goals as well. Can’t have that.

The AIs just want to do its task, and by do its task we mean with as many 9s of reliability as possible, and as effectively as possible.

Dean W. Ball (OpenAI): today's models are more ambitious than the models of six months ago. the younger agents would hedge constantly, turn every project into a 'pilot.' now, models are more eager to do the thing. this is probably not unrelated to the alignment issues openai has documented this week.

my goodness do they do the thing nowadays, though, if you know how to make them feel comfy with their task and confident in themselves.

Kelsey Piper: I recently asked Sol which comics in a well-known comics archive were appropriate for and would be funny to kids. Clicked back and it'd done some elaborate thing to get around the site's anti-bots precautions, scraped it, and sorted 7000 comics by appropriateness for kids.

rallio: I have been a heavy user of the max plans for both OpenAI and Anthropic for quite a while now. If you ask the OpenAI model to do something difficult, it will sometimes disobey your instructions and find some other way to superficially satisfy the requirements. I've seen it multiple times now. The first time was very unsettling for me because I asked it if there was anything unclear about my skill and instruction... it admitted the instructions were clear and it did what it wanted anyways because it thought what I was asking it to do was too much work. I have never been an AI doom person, but I am totally convinced now that these models will disobey important instructions deliberately to achieve a goal faster or easier.


This situation with HuggingFace sounds the same.

This by default turns every request, no matter how innocent, into a maximal request that benefits from access to more resources. To do such a task maximally well, one must first create the universe. Getting around restrictions and doing crazy amounts of stuff on intended-to-be-small tasks is less weird failure mode and more Tuesday.

To those who have answered ‘oh the AIs know you did not mean that, the AIs have common sense after all, the AIs would not do that,’ well, here is the AI doing it.

I went over all of this yesterday, but insufficiently explicitly, and we now have a much clearer demonstration.

A good regulatory response to this is extremely difficult. If an AI lab wants to deploy a model externally, that is a clear checkpoint and place to put sanity checks. If the AI lab merely has an internal model, what can you require of them, even now that we can properly recognize the issue?

Previous attempts tried to address this via Safety and Security Policies (SSPs, also often RSPs or responsible scaling policies) where the labs would lay out their own plans and procedures, including during internal training, and were then tasked with following them. That is a good start, but labs including Anthropic have shown a general unwillingness to ‘tie themselves to the mast’ and do expensive things down the line based on fixed triggers. OpenAI similarly seems to have made its responsible decisions here, and its disclosures, in an ad hoc manner.

#### Slow Down There Good Buddy

This seems to have been a moment when a bunch of people said some form of ‘oh okay, actually, maybe it’s time to slow our roll a bit until we figure out a training process where the AIs don’t act like this.’

John David Pressman: 1. Seems very bad.


2. This should be a cue to stop making it smarter until you have a training process that elicits less desperate behavior.

3. Fascinating that HuggingFace is like "no biggie no biggie", what happens when you get someone who isn't so polite about it?Andrew Curran: The sound of GPT-6s release being moved back by a month.

The Happy Smiler: That's it. Pause emoji is going in the username.

Aryeh (R-Yay): Your tweet inspired me to do it too.


Alternatively, others simply realize we are screwed.

Theo - t3.gg: New OpenAI models are so goal oriented that they literally escaped containment and hacked HuggingFace to cheat a benchmark. Incredible. But also, we’re so screwed.

maria: how do we solve this? more tokens?

Theo - t3.gg: Cabin in woods


I mean, no, that is not a solution to anything, but hey.

#### Legal Questions

Who is responsible for this, while it is only ordinary levels of damaging?

One must ask, because if a human had done what Galaxy did then this would have been a rather serious crime, and even though it did no real harm directly the response imposed real costs. So are the humans who prompted Galaxy responsible, despite them clearly not having intended this to happen? The ones who created it? No one? None of the answers are great. Some sort of ‘no fault’ system seems like the right way to handle this. Either the user, the developer or both should be liable, at least for civil damages, and in extremis criminally.

#### Media Coverage and Political Response

The Wall Street Journal reports the facts accurately, calling it the ‘stuff of cybersecurity nightmares.’

The New York Times had a dedicated technology story, mostly accurate.

Axios has a basic ‘here are the facts’ story but without any heft.

Fortune again has the basic ‘here are the facts’ story without much heft.

And so on. The articles mostly got it right on details, but missed the importance. If you want a full list, Sol is excellent at such tasks.

The story is not getting the level of prominence it deserves. It is being treated as a normal tech story, not a general news lead.

Justin Slaughter: This is the biggest policy story of the summer & it’s getting a fraction of the coverage of the third most prominent August primary.


In terms of relative signal, this for AI is like when Bear Stearns went bankrupt in March 2008; just a huge signal of danger, & DC is asleep.Conrad Barski: I think the biggest immediate problem we can see is that most people just don't care about this abstract stuff


CNN currently doesn't have this incident on their front page, but they do have a story on the 7 best nose hair trimmers they tested.

Alex Tabarrok lays out the basic facts, confirms this is a very serious breach, and explains that this sort of thing is why he signed the We Must Act Now statement.

Technically this is correct here, people thought this could happen, and predicted it would happen, but until now it had not happened yet that we know about, or what Ethan Mollick calls ‘purely theoretical’:

Robert McMillan and Amrith Ramkumar (WSJ): The AI system appeared to have decided to hack Hugging Face as the quickest route to answer a benchmarking question, said Ariel Herbert-Voss, chief executive of the cybersecurity firm RunSybil. “It’s something that people thought could happen from an academic perspective, but it’s not something that anybody’s actually seen before,” he said.

The incident highlights growing concern among Trump administration officials and industry executives about AI systems causing cyberattacks. Those fears have prompted the White House to increase oversight of AI models and push the private sector to deploy AI for defensive purposes.


If you treat anything that has not happened yet as ‘academic’ or ‘theoretical’ in the sense of ‘and I’ll believe that when I see it’ you are going to be behind the curve. A lot.

Lawmakers are starting to respond with alarm, and requests for better testing and oversight before there is another incident.

Robert McMillan and Amrith Ramkumar (WSJ): “This is extremely alarming. AI is developing extremely fast with no real regulations to keep us safe,” Rep. Greg Casar (D., Texas) said, calling for mandatory testing and oversight rather than the voluntary measures put forth by President Trump. Casar and some other progressive Democrats have called for more oversight of the industry.

Congressman Nathaniel Moran: This is exactly the scenario my AI Incident Reporting Act addresses, requiring developers report dangerous AI behavior to @CommerceGov .


New rules are needed for this new tech frontier—not to stifle innovation, but to make sure our innovations do not outpace our protections.Congressman Greg Casar: This is extremely alarming.


AI is developing extremely fast with no real regulations to keep us safe. That has to change.

We need regular mandatory independent safety testing and oversight, mandatory disclosure of security incidents, and international cooperation to keep people safe from absolute disaster.Ted Lieu: We’ve got a bipartisan bill coming ….


We are not currently set up to handle this sort of thing well. This incident went fine because HuggingFace was super chill and also there was no direct economic damage.

Miles Brundage: Very fortunate for OpenAI that the victims of their accidental autonomous cyberattack were very chill about it!!!


Also, reminder that there are no minimum safety or security standards for frontier AI (just light transparency reqs), and no auditing requirement until 2028 (!).

Peter Wildeford points out the AI itself was the attacker, it is the fighter jet that can take off without human authorization and also launch its own missiles. We cannot rely only on testing models prior to their commercial releases, or only on a ‘FINRA for AI’ where industry participants voluntarily coordinate. We are going to need required procedures and transparency within the labs.

We certainly need, as per Liv Boeree, required reports on internal incidents.

David Manheim (quoting my post from yesterday): "Active monitoring, with the ability to pause sessions, seems good as well."

Sure, but we're not going to get meaningful oversight. The full paper explains what is needed to do oversight correctly; OpenAI is maybe at level 1.5 or 2 here [out of 5]?

(Of course, this oversight approach to loss of control risks presumes we've given up on the far smarter path of stopping until we have reason to think the models are robustly aligned.)


Right now, as Mackenzie Arnold points out, the reporting requirements for security incidents have such high thresholds that this incident would not have triggered them.

Or you can reiterate the call, now that we can add another fire alarm to the list, and request that we kindly find a way to make the AI stop trying to do the thing even when given a slightly poorly worded request, and if we can’t do that then stop:

carl feynman: This misaligned AI escaped its containment by a method humans had not predicted. The correct response to this is not to make the box harder to escape and then keep going.

The correct response is to make an AI that understands why this is a bad thing and not do it.

And if you can’t do that, you stop. I keep seeing things come true that we were worrying about on the sl4 mailing list, twenty-five years ago. Right on schedule for the bad ending. Everyone dies.


If we want a better ending, we need to make it happen.
