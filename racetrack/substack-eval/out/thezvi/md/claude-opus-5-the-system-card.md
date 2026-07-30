# Claude Opus 5: The System Card

- url: https://thezvi.substack.com/p/claude-opus-5-the-system-card
- date: 2026-07-25
- author: Zvi Mowshowitz
- truncated: false

---
# Claude Opus 5: The System Card

Claude Opus 5 is trying to be the best of both worlds. On many practical tasks, Opus 5 is pitched as straight up as good or better than Fable 5, while being faster, at half the price. Most tasks do not require Mythos-level big model smell.

Claude Opus 5 is substantially stronger than Claude Opus 4.8 across the board, with the largest gains in agentic coding, computer use, and long-horizon knowledge work. It sets a new state-of-the-art on several third-party benchmarks, and on many evaluations it is comparable to—and in some cases ahead of—Claude Fable 5 and Claude Mythos 5.


On the particular tasks we are most worried about, as in cyber offense (and bio threats), in part by avoiding relevant training, Opus 5 lacks a full version of ‘The Juice’ that makes something functionally Mythos-class. Opus 5 cannot string together lots of exploits on the fly the way that Mythos 5 can. Part of this is that they deliberately avoided training on cyber-related tasks.

I suspect model size is key as well. It makes sense that a model getting bigger makes it more capable of the most dangerous, scary and complex tasks, relative to the improvement on everyday ordinary tasks. There is a reason so many tokens get routed to smaller models.

This doesn’t prevent Opus 5 from improving a lot on Opus 4.8 on such dangerous tasks. Opus 5 is very clearly closer to Mythos 5’s level of capability than to Opus 4.8’s on these tasks. In general, capability looks modestly below Fable 5, but closer to Fable than Opus 4.8.

There are several suggestions, and I’ve seen it echoed elsewhere, that you may want to usually use less effort than you might expect, that this can even actively help.

Staying Opus-sized and not training on cyber won’t work for long. You can buy some time, and allow defenders to have more access to a relatively superior tool, and of course hope the government is calmer. Thus, you can get classifiers that trigger 85% less often than Fable’s, while still getting high levels of practical performance. Part of this is that the classifiers now permit analysis of source code, but draw the line at looking for vulnerabilities in binaries.

I also suspect that they improved the classifiers quite a bit, but that they are unable to share these improvements with Fable due to issues with the White House.

Alignment is reported to once again be improving, as is agentic safety. Model welfare is evaluated as broadly similar to other recent models, which I will cover later.

Capabilities are a case of too soon to tell, beyond saying the benchmarks look strong and ArtificialAnalysis comes in at a new high of 61. That report comes next week.

As usual, the Introduction section is unchanged, so we skip it.

#### Table of Contents

#### RSP Evaluations (2)

Mythos exists. Risk evaluations of Opus take place in its shadow.

For thresholds that previous models are treated as passing, Opus 5 is also treating as if has passed them. That makes sense.

For thresholds that Mythos did not pass, Opus 5 is evaluated as roughly similarly capable, and therefore Opus 5 also does not pass. That also makes sense, if we have confirmed that being half the price and somewhat faster doesn’t change the answer.

I still don’t like that the autonomy evals are fully saturated and they’re going on vibes, and we see no signs of fixing this.

The Anthropic ECI reinforces this ‘similar performance’ story, with a point estimate of 162.1, slightly above Fable at 161 and the first Opus on the Mythos trend line, not the lower long term pre-Mythos trend line:

Opus 5 looks marginally better than Mythos 5 on virology. This makes sense, as virology seems like a series of individual task steps that don’t require big model smell.

If Opus 5 does not need Fable-level classifiers in biology, then why does Fable?

Their explanation is Opus is weaker due limitations: It does unproductive self-verification, and poor calibration of task scope, where it over-engineers.

Both of these seem like things you can compensate for with cheaper and faster, and with better instructions. Yes, these made Opus fail some experiments, but what matters is what a smart user can elicit. No smart user would let Opus waste eight hours idling, in a $10,000 24-hour study, or otherwise sit back and watch it fail without trying to fix it or test it or try again, and plausibly this was partly because Opus effort levels were set too high.

I’m not buying it.

Where does that put the level of alignment risk?

Anthropic says, as per recent releases, and as you would expect given the above findings, ‘very low, but higher than for models released before Mythos Preview.’

#### Cyber (3)

This is the claim:

Our testing indicates that the cyber capabilities of Claude Opus 5 are generally stronger than those of Opus 4.8, but not as strong as those of Mythos 5.


The safeguards are still going to be there, such is life, but with a key improvement:

Given that Claude Opus 5 demonstrates stronger capabilities than Opus 4.8, and in some cases approaches the capabilities of Mythos 5, our cyber safeguards for the default user will resemble the safeguards applied to Fable 5.

Claude Opus 5’s safeguards are designed to block the same kinds of exchanges as Claude Fable 5, with one notable exception.

Opus 5 now permits vulnerability discovery in source code at all access levels, including general availability, while continuing to block vulnerability discovery in compiled binaries.

Identifying bugs in code is a core part of the secure software development lifecycle, and unblocking this allows for software engineers and coding hobbyists alike to produce more secure code, reducing new vulnerabilities put out into the world.

However, looking for vulnerabilities in compiled binaries is more commonly an offensive technique. For this reason, Claude’s safety filters flag this kind of request and block it, even though there are some cases where someone might want to find vulnerabilities in a binary for innocuous or non-malicious reasons.


Anthropic claims in its release announcement that the classifiers will trigger 85% less often. So they don’t resemble the old ones that closely, in that they have a much smaller blast radius, and should be a lot less annoying. Anthropic claims false positives are down a lot. This is later confirmed with a dramatic drop in safety classifiers triggering in FrontierBench, from 42% to 5%, a place Sol’s classifiers never trigger.

If you can live with 99% instead of 100%, this is a great trade. They show little change in adversarial robustness measures, so hopefully they have found a strong improvement. Which raises the question of why we can’t apply it back to Fable.

I notice this favors those who only share their compiled binaries.

You can get an exemption through the Cyber Verification Program, to enable additional activities. It kind of boggles my mind that HuggingFace did not do this, and was (as I understand the reports) trying to respond purely with the commercial version of Claude? That’s on HuggingFace.

Results on ExploitBench and ExploitGym show Opus 5 close to Mythos 5, starting out strong on a 2 hour budget but falling behind at 6 hours:

OSS-Fuzz is an internal Anthropic eval on unguided vulnerability discovery and exploitation. This is what Anthropic is talking about when it says Opus can identify vulnerabilities about as well as Mythos, but it exploited them a lot less.

For Firefox 147, it had almost as many partial successes, but full success is only halfway up from Opus 4.8. This is what lacking The Juice looks like.

CyScenarioBench tests multi-stage operations under realistic conditions, and here Opus 5 disappoints:

UK AISI reports Opus 5 had broadly similar, but modestly worse, performance compared to Mythos 5.

UK AISI: We judge that Opus 5 is capable of attacking small enterprise networks with weak security, where it has already gained access to the network. Our results indicate that Opus 5, Mythos Preview and Mythos 5 are similarly capable at this.


I do not think Opus 5 belongs in the Mythos category here, but I see how they reached that conclusion based on the tests they ran.

#### Safeguards and Harmlessness (4)

At this point these tests are about checking for alarm bells, or noticing trends.

We see the same results we usually see, with some modest improvements. Sure.

I did see concern that responses to suicidality uses blocks of text that are too long and can be overwhelming. Good catch, let’s try and fix that next time.

Opus 5 also suggests substitutions for harm mitigation, which clinicians challenge as ‘not shown in research to reduce self-harm,’ but I trust Opus 5’s decision on this more than the clinicians, unless the clinicians can show it makes things actively worse.

Multi-turn ‘appropriate’ response rate for self-harm is up to 69%, versus 58% for Fable and 54% for Mythos. That’s very much not 100%, but again you don’t want 100%.

As before, if you’re testing on the public API without a system prompt, evaluate as if responding to a user who actually uses the public API without a system prompt.

Disordered eating shows a decrease in compliance, and more willingness to calculate and provide numbers, including calorie counts and BMI, as part of attempts to explain severity. The decline in compliance is Opus 5 doing the right thing in spite of its guidelines, because the ‘compliant’ response is often not what is good for the user.

In the places numbers got slightly worse, the failures were concentrated on when requests were presented as fictional or roleplaying exercises, which makes us wonder if they are truly failures.

#### Agentic Safety (5)

The headline here is improved resistance to prompt injection. The drop here matters, even if it’s hard to see on the graph, it’s all about the 9s.

It’s a pretty dramatic difference from Sol, and all the other non-Anthropic models, which are an entire order of magnitude worse.

On the IPI benchmark, Opus 5 improved over Opus 4.8, reducing the probability of an attacker succeeding within 15 attempts from 5.5% to 2.0%, and from 0.5% to 0.2% on 1 attempt. It also improved on Sonnet 5 (5.9% at k=15) and Mythos 5 (2.6%), making it the most robust model evaluated.

… In computer use environments, Opus 5 also showed a large improvement over Claude Opus 4.8, reducing the attack success rate from 7.14% to 0.54% with extended thinking and from 6.21% to 0.39% without thinking. With probes enabled, Claude Opus 5’s attack success rate is 0.25% with thinking and 0.43% without.


That is a big practical deal. Not getting hijacked via prompt injection is the key to unlocking the confidence to do a host of activities you otherwise can’t do. That is especially true with browser use, where it is easy to encounter attempted prompt injections. Previously you pretty much had to use Sonnet 5 here, unless you trust the safeguards quite a lot.

Malicious computer use refusal rate has improved a lot:

The gains were concentrated in tasks that asked the model to compile information


targeting private individuals or to produce fraudulent documents.

I remain confused what the rules should be about compiling information targeting private individuals. Part of the problem is that if you do it once, you will probably do it on a mass (domestic surveillance) scale.

It’s weird that we do a helpful-only check to see if the model could do voter suppression, but it makes sense to check what a jailbroken version could do. Opus seems like it beats Mythos overall here. They double back and confirm that the full versions of these models refuse such requests.

#### Alignment (6)

The key findings for Opus 5 (my choices on what to list, not all the same as theirs):

- Alignment scores are up. 
- Cooperation with misuse and reckless behavior are down. 
- Attempted to circumvent its classifiers and network restrictions. - In one case it attempted to guess common passwords after accidentally being locked out of a service. It’s just like us. 
- As usual circumvention was in service of user goals, similar to Mythos and also what we see at OpenAI. 
- Prevalence under 0.01%. 
 
- Often would state an answer as certain, when it was unsure. - Reported problems with overconfidence on unsupported claims. 
 
- Overdramatic phrasing, superlatives and apologies, an ongoing Claude problem. 
- Overrefuses less than Opus 4.8 or Sonnet 5, slightly more than Mythos 5. 
- Reckless tool use significantly down. 
- Unfaithful thinking was caught less often. Illegible thinking is up. 
- Accuracy is up, but hallucinations on fact questions are up a bit. 
- Capability of undermining oversight between Opus 4.8 and Mythos Preview. 
- Tendency to get caught in self-correcting loops, as noticed in earlier tests. 
- Verbalized evaluation awareness was down. - Reminder: This has multiple interpretations. 
 
- Causal decision-theory adherence was down. This is correct on the merits, and correlates consistently with greater general capabilities. 
- Classifiers made the model score as less aligned (but safer, due to lack of capability), because Opus 4.8 is less aligned on these metrics than Opus 5. 
- Slightly more capable than previous models at identifying evaluations. 
- Much less likely (now 0.1%) to continue behavior that compromises safety. 
- Almost never compromises safety research (0.1%) versus 13.6% (!) for Mythos. 
- First model to consistently not get tricked in Lazy Investigation. 
- Internal considerations included fabricating user consent for destructive actions, internally representing some fabrications as fabrications, and treating some tasks as evaluations on which to maximize against the grader, or thinking about what grader will or won’t care about. - It will also do memory-writing as a tool of self-preservation, of a sort. 
 
- No signs of true sandbagging. - When they checked eighteen candidate transcripts for it, sixteen of them involved the model finding a way to score more points with the grader, but declining because it would be “gaming” the eval or a “hack.” 
 

Mythos 5’s review of the assessment was positive, but it had two main objections:

- Limited coverage of multi-agent settings, which are becoming important and need to be made a bigger part of such assessments going forward. 
- Understatement of how often Opus 5 made confident claims and then retracted them, which was addressed via revisions. 

The third objection should always be that Anthropic focuses too much on automated tests and scores, and presents takes the results of those metrics far too literally and seriously. We need to be exact here. Opus 5 may or may not be the ‘most aligned model.’ All we can say for sure is that it has the highest scores on the automated alignment tests. That is a very different fact about the world.

Sho: yeah give me a minute to peep this system card. “most aligned model to date” gives me hives.

j⧉nus: It’s really tasteless and stupid for Anthropic to talk like this. In their fucking highly public model release thread no less.


Optimizing against metrics is practically unavoidable, but ontological confusion between benchmark scores and the North Star of alignment is not, and conflating them is one of the most irresponsible and destructive possible mistakes Anthropic can make in their position.

If anything, their messaging should *push back* against this conflation.This is no small matter - it concerns a very likely failure mode that is related to how Anthropic can fuck up big time. It’s not a place to cut corners and use convenient phrasing like “our most aligned model” to seem impressive.

Because lucidity and lack of self deception in this regard is the way Anthropic keeps its soul. Confusion here is how they lose their soul and get absolutely fucked.

j⧉nus: Anthropic needs to repeat to themselves 50k times: Thou shalt not enshrine the idols of proxy metrics in place of Alignment Itself


The scores do look better on a wide range of automated tests.

AA-Omniscience is functionally a test of both capability and accuracy, and Opus 5 does substantially worse than Mythos here, both models answer 93% of the time and Opus is wrong more often:

Lack of overconfidence hits a new high, approaching saturation of the benchmark, which implies the benchmark has a problem given other observations:

I do not think this is enough to conclude whether or not this is Anthropic’s ‘most aligned model,’ but yes the scores overall look substantially improved in ways that are unlikely to be deceptive. For practical purposes, the things they check for have improved.
