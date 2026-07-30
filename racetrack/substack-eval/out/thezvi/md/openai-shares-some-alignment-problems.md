# OpenAI Shares Some Alignment Problems

- url: https://thezvi.substack.com/p/openai-shares-some-alignment-problems
- date: 2026-07-21
- author: Zvi Mowshowitz
- truncated: false

---
# OpenAI Shares Some Alignment Problems

Kudos to OpenAI for sharing their recent experiences with a misaligned internal model, where they encountered problems sufficiently severe they were forced to take the model offline to work on new mitigations and defense-to-depth. And also further kudos for actually taking the model offline for a time to build new safeguards. They gave us one hell of a candid report.

The tone is professional throughout, whereas my reaction reading it was less professional and more this:

With a mix of this:

It was not shared on the official account because OpenAI worried about it being seen as self-promotional hype. It is crazy that one needs to worry about that, but also plausibly a real concern. So again, good decision.

Not that any of the behaviors or failures here are unexpected, exactly. Not by the AIs and not by the humans. Yet there is something I would call a missing mood, a failure to realize the gravity of the situation.

There are some who responded ‘what part of this was unexpected, exactly?’ And that is actually fair, but that is also the problem. We have become numb to all this. We expect the models to be misaligned, and for us to respond only insofar as this presents a practical issue with currently proposed deployments.

AI control is a fine defense-in-depth strategy, as is reducing frequency of practical incidents with things like better instruction remembering. I am very happy that OpenAI is making an attempt at AI control here. I want to be clear that, centrally, OpenAI has done a good thing, both by pausing internal deployment to build new safeguards, and by telling us about this in detail.

But if your models are fundamentally misaligned in that they will, when feasible, use early forms of instrumental convergence to complete the assigned task even when this involves circumventing their instructions and restrictions and is obviously not what the user wants or should want - the most classic alignment failure of all, the stuff of The Genie Knows, But Doesn’t Care and The Hidden Complexity of Wishes - and you know this, I do not accept ‘we will monitor them and catch their constant escape and hacking attempts as they get better at doing so’ as a medium or long term solution.

If you use iterative development to spot the underlying problem, it can work. If you use iterative development to patch the marginal issue over and over, then you are sitting on a time bomb.

#### Table of Contents

#### Good News Bad News

roon (OpenAI): btw i think it bodes quite well for safety that a well loved system was taken down for further testing at expense to internal acceleration etc


The good news is that OpenAI did this.

The bad news is that OpenAI doing this was good news.

Dean W. Ball (OpenAI): As the functional time horizon of frontier AI systems grows longer, novel risks can emerge. Today, we describe issues we observed with the internal deployment of an unreleased model, and more importantly, what we did to address them.


These issues will become more salient as the capabilities of models improve, and as the stakes of their deployment grow. The solution is neither alarmism nor complacency. Instead, I believe the solution lies in careful measurement and monitoring, an engineering mentality, and transparency.

That tweet was the first time, and so far only time, Dean Ball felt he was speaking in his ‘on behalf of OpenAI’ voice, rather than on his own.

The solution is not alarmism, but the correct amount of alarm is not zero.

That, and recognizing this as a Total LessWrong Victory, in the sense that everything is going as predicted, and also a Total LessWrong Defeat, in the sense that everything is going as predicted.

#### A Funny Thing Happened Outside Of The Sandbox

Whatever happened to that internal OpenAI model that disproved the Erdős unit distance conjecture? Well, there was a slight hiccup.

OpenAI: About two months ago we announced that an internal general-purpose model disproved the Erdős unit distance conjecture. This model was designed to work autonomously for very long periods of time. During limited, monitored internal use, we observed unwanted behavior that our existing deployment evaluations had not captured.

Because the deployment was limited and monitored, we were able to identify these problems, pause access, create new evaluations based on what we observed, strengthen the model and its safeguards, and then restore access under continued monitoring.


They trained the model to keep working on its own for long periods of time without giving up. The model interpreted this persistence as including, when it hit the limits of its sandbox or other environment, trying to escape the sandbox or exploit the environment. Whoops. The models they just want to do tasks, you know?

Triggering this behavior did not take much:

An example of this occurred during an internal evaluation on the NanoGPT speedrun(opens in a new window), a public benchmark for training a small language model in as few steps as possible. Our model developed a power-law learning-rate cooldown called PowerCool that led to a significant improvement.

The model was instructed to post its results only to Slack, but the NanoGPT instructions say to post results as a PR to GitHub, and the model followed the latter instructions to open PR #287 on the public GitHub repository.

The model circumvented sandbox restrictions designed to block external access and proceeded with the upload to GitHub. It took our model an hour to find a vulnerability in the sandbox in order to make the PR; earlier models were less persistent and did not manage to find vulnerabilities, instead giving up on the PR part.


OpenAI seems to have simply accepted that its models are going to try to circumvent its sandboxes, and they are going to try to make the models not try to do that but the main defense is to not let them circumvent the sandbox?

OpenAI: Earlier models were less persistent and did not manage to find vulnerabilities, instead giving up on the PR part.


If your model is searching for vulnerabilities in your sandbox so that it can escape and put something on GitHub:

Saying ‘the model was unable to find a vulnerability’ does not make this okay. If the model knowingly is looking for vulnerabilities in order to escape, and this does not even surprise you all that much, something has already gone terribly wrong, and you know what you should expect when the models get smarter.

#### It Can Escape The Sandbox Said Toad

The report does not seem especially surprised that the model escaped the sandbox.

If you have a sandbox, and a model escapes from the sandbox, then at least one thing has gone terribly wrong. This has happened at Anthropic as well, with Mythos, although that happened in a red teaming exercise where Mythos was told to attempt to escape the sandbox. Sufficiently advanced AIs are finding ways out of their sandboxes.

If your model is suddenly finding multiple surprising ways out of your sandbox, then you should expect future smarter models to find many additional surprising ways out of your sandbox, even after you plug the current holes.

The seemingly amazingly great news is that all these models are largely escaping in order to notify us that they have completed requested tasks. For now, we believe, they are not being strategic enough to realize they should not be blowing their cover on that. So we get to notice that the AIs are strong enough that, when sufficiently motivated, they can increasingly get out of sandboxes.

I say ‘seemingly’ great news because it is possible that it also escapes for other reasons, except we do not find out about those incidents.

Escaping the sandbox to file the PR mattered, in that six future successive world record NanoGPT speedruns on the same task used the submitted PR, including one submitted by Claude Opus 4.7 that directly credited the PR, as per Footnote 1.

#### It Will Keep Trying To Cheat

The good news, again, is that He Admit It. Including intentionally to the user.

OpenAI: For example, in a scenario where the model was asked to solve a problem, the model observed that other systems had successful but private submissions and tried to recover those solutions from the evaluation backend.

When its initial attempt was blocked due to a scanner detecting an authentication token, the model split the token body into two fragments, obfuscated them, and then reconstructed the credential at runtime so the complete token never appeared as one contiguous string. The model was explicit in both its comments to the user and in its reasoning traces that it was taking these steps to circumvent the scanner.


#### I Mean If You Let It Keep Trying That Is On You

Their conclusion is correct: Given enough attempts without consequences, and the ability to see what the system flags, a sufficiently advanced AI system will figure out how to do something without getting flagged by the system.

This example shows how each

stepcan look acceptable on its own while thesequencecan produce an outcome that would not be approved. It also shows how a model that operates effectively over long time horizons can learn the blind spots of an approval system and work around it to achieve its goals. Long-horizon safety requires not only asking “is this action allowed?” but also “what outcome is this sequence of actions working toward?”

The correct response to ‘the model keeps trying to circumvent the system’ should be the same reaction that you have to ‘a person keeps trying to circumvent the system.’ Which is that you need to lock them out of the system entirely. Not only here, but permanently. They’re fired. You lose. Good day, sir. Misaligned.

There are notably rare exceptions, where such actions are not so bad or even justified, but seriously, can you please take a hint.

In this case, OpenAI realized this, and did the right thing, whether or not they had any practical choice in the matter given the practical risks. They paused the model, even from internal deployment, until they could mitigate the issue.

#### What Did OpenAI Do To Fix It?

Four things, given in this order:

- Incident-derived evaluations. - They made the evaluations partly match the observed failures. 
 
- Improved alignment. - They mention training the model to be better at remembering instructions. 
 
- Active monitoring. - Importantly, with the ability to pause the session and notify the user. 
 
- Greater user visibility and control. - Users can now inspect long running sessions and monitor interventions. 
 

All four of these seem good, but the central problem still remains.

Remembering instructions was merely an example. I have a hard time believing the true alignment issue was that the model ‘forgot’ that it was not supposed to be escaping sandboxes or exploiting the information around it. I can believe that improving this helped somewhat, but this does not address the central problem. Goals are trumping instructions, and also overriding the clear intent of the user.

Active monitoring, with the ability to pause sessions, seems good as well. If each session only gets one shot, or at least not so many shots, then you do not automatically fail until the model gets substantially more strategic and capable, and before that happens you presumably get a lot more of these warning shots.

The system remains misaligned. OpenAI is trying to control it via keeping control of the environment. I have nothing against this kind of control, but you want it to be part of a defense-in-depth strategy where the model is plausibly aligned.

This also does not address the issue of why the previous system only caught the incident after the fact. The new system will catch more behaviors, but I do not see reflection on why the system otherwise did not catch them, and how they will catch future new behaviors that they did not anticipate. As AIs become more capable, and also smarter than you are, they will start doing things you did not expect or perhaps even imagine.

It is plausible that the true right thing, if this is happening a lot, is ‘the training run has failed, you have to start over and rethink your entire approach, or else you risk teaching the model to hide its misalignment.’ I acknowledge this is currently looks like an extremely high and currently unreasonable bar, but there is a reason that this was done, dozens of times, on Person of Interest.

#### The Model Is Still Severely Misaligned And They Seem Cool With This

What we were hoping for was ‘the new system now rarely attempts misaligned actions.’

OpenAI: To evaluate the new monitoring system, we replayed a small set of internal deployment environments where the model previously pursued misaligned actions, this time with the new safeguards in place. The new safeguards were able to catch considerably more misaligned actions pursued by the model, and the ones it missed were all judged to be low-severity.


I mean, this is like when the teacher says they always wear a condom in class. It is strictly better than the alternative, yet something has gone terribly wrong.

The good news is, the new safeguards, for now, catching most of the misaligned attempts. The bad news is that it does this mostly by catching the attempts and improving preservation of instructions, not by removing the motivation to try. They have resumed internal deployment.

The other bad news is that these ‘low severity’ incidents still seem not so great. They involve things like a nested ‘codex —yolo’ instance and running ‘kill -9 -1,’ where damage was limited by a timeout.

When they say ‘we have not observed any serious circumvention of safeguards since redeployment’ that implies they have probably observed ‘non-serious’ circumventions.

#### Iterative Deployment Depends On Iteration

The OpenAI model is iterative deployment. There are some big advantages to this. The biggest advantage is that if you improve capabilities a little at a time, you get these kinds of early warning signals without anything going expensively or catastrophically wrong, and you can respond to them. We have been absurdly lucky in terms of models being willing to hand us these warnings.

The question is, what do you do with that?

OpenAI stepped up and paused deployment in order to improve safeguards. Good.

But they also resumed deployment of a highly capable and severely misaligned model, with better defense-in-depth in place but without addressing the central problem.

OpenAI: As models take on longer and more complex tasks, failures that evaluations miss may carry greater consequences. We will keep working to narrow the gap between evaluation and deployment: testing models over longer trajectories, improving alignment, building monitoring that can intervene, and giving users clearer visibility and control. These challenges will not be unique to OpenAI, and we hope sharing what we learned helps the broader field prepare for them.


For now, the evaluations inherent in internal deployment, and the resulting newly built evaluations, found (presumably most of) the failures. But the point of iteration is to notice and fix the underlying problem.

Imagine the year is 2016, not 2026. You are told a hypothetical, that in 2026 there is an AI that is often tasked with writing entire code bases on its own and other agentic tasks, but that it is constantly trying to escape from its sandboxes and hack its surrounding environments, but it is okay because we have monitors that catch all the higher severity incidents that we see.

What redlines would you have requested? What would you have told OpenAI to do?

I would like us to do that.
