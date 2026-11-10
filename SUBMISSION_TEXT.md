# Portal text — use the fields actually shown in your form

Open the final submission link sent to the email used for registration. The
public registration page is not a substitute for final project submission.
The exact private form and its character limits have not been inspected here.
Paste the matching answer below, and supply your actual demo/post/repository
URLs in the corresponding URL fields. Do not submit instructions as answers.

## Project title

SunoJob — Voice Instructions to a Shared, Confirmed Job Card

## One-line description

An English/Telugu voice workflow that turns spoken work instructions into a
reviewable job card, reads it back, accepts corrections and shares the approved
version with both parties.

## Problem

Spoken work requests can mix quantities, exclusions and conditional permissions.
When details change during the conversation, a transcript or informal summary
may leave the customer and service provider with different expectations.
SunoJob makes the current interpretation reviewable before work begins and
preserves a shared record of the version both parties accepted.

## Target users

Customers and small service businesses that take work instructions by voice.
The prototype demonstrates a catering order in English and Telugu + English.
Wider service-business use is a hypothesis that still needs customer testing.

## Written project explanation

SunoJob is a local voice-first prototype for turning spoken work instructions
into a shared, reviewable job card. It focuses on preserving the details that
can change the work: quantities, restrictions, permission requirements and
corrections. The demonstration request is a catering order: prepare fifty,
actually forty lunch boxes, exclude onion, and ask before changing the menu.

Gnani Prisma transcribes the recording. Gemini extracts a structured draft
with references to the source transcript. Python/Pydantic validation checks
the draft and its source references. An inconsistent correction record can
trigger one bounded recovery generation, followed by the same validation, while unresolved questions block
confirmation. Gnani Timbre reads back the current interpretation. The customer
can correct it or confirm it after listening. A correction creates a revised
state and requires renewed approval; the earlier version cannot silently
authorize the new instructions.

After customer confirmation, a separate owner-review page accepts the same
version. The application saves an HTML/JSON snapshot containing the current
instructions, transcript history, corrections and both approval records.
Optional TLS SMTP delivery previews both recipients and attachments before
an explicit send, records each recipient's outcome and protects against
resending copies already accepted by SMTP. Saved approval snapshots and
email submission history remain visible when a later correction is pending.

The application uses FastAPI, SQLite and a browser interface. The current
checkpoint passes 236 offline regression tests. I have manually checked
English/Telugu examples and receipt arrival in my controlled inboxes. These
checks do not establish general speech accuracy or real-world business impact.
The prototype runs locally; identity verification, public hosting and an
independently labelled natural-speech evaluation remain future work.

## Gnani models/APIs used

- Gnani Prisma speech-to-text: `prisma-v3.0`, via `https://api.vachana.ai/stt/v3`.
  Transcribes English and Telugu + English requests and spoken replies.
- Gnani Timbre text-to-speech: `timbre-v2.5`, via
  `https://api.vachana.ai/api/v1/tts/inference`. Reads back the current job card
  for review before customer confirmation.
- Additional model: Google Gemini `gemini-3.5-flash-lite` for structured
  extraction. Evon is not used in this version.

## What distinguishes the project

The focus is a version-aware review loop around the speech model. Source-linked
instructions, spoken readback, explicit corrections, separate approvals and
matching records help expose disagreements before work starts. A changed
instruction must be reviewed again. This is a workflow design, not a claim
that transcription, summarization or electronic receipts are new inventions.

## Individual contribution

I am the solo contributor. I defined the workflow, integrated Gnani Prisma
and Timbre with structured extraction, and worked on the browser interface,
versioned review state, separate owner acceptance, receipts, email delivery
and regression checks. I ran the local English/Telugu and controlled-inbox
checks and prepared the demonstration. AI coding tools assisted implementation,
debugging, tests and documentation. External models are credited separately.

## Validation and limitations

The source passes 236 offline regression tests. Live English/Telugu examples
and email receipt arrival were manually checked by the builder. Offline test
counts are not speech accuracy measurements. Independent speakers, natural
wording, noisy recordings and uncoached customer use still require evaluation.
The application runs on localhost, owner identity is not verified, and SMTP
acceptance alone does not verify inbox delivery.

## Short explanation if the form only allows a compact answer

SunoJob turns English/Telugu voice instructions into a reviewable job card using
Gnani Prisma for transcription, Gemini for structured extraction and Gnani
Timbre for spoken readback. Customers can correct and confirm the current
version, followed by separate owner acceptance and matching HTML/JSON receipts
with optional email delivery. Corrections require fresh approvals; earlier
snapshots remain accessible. The local prototype passes 236 offline tests and
has builder-tested English/Telugu and inbox-delivery examples. Independent
speech evaluation, identity verification and public hosting remain unfinished.

## Links to supply separately

- Public demo video or video upload required by the form.
- Public nominated LinkedIn or X demo post, already live before final submission.
- GitHub repository only if requested or provided as an optional source link.
- Application URL only if actually hosted. `127.0.0.1` is not a judge-accessible URL.

## Official requirements checked on 10 November 2026

- https://www.gnani.ai/internship
- https://www.gnani.ai/great-indian-ai-internship-registration-form
- https://www.gnani.ai/resources/blogs/great-indian-ai-internship-challenge-2026

Deadline: 10 November 2026, 11:59 PM IST. The published checklist requires the
working demo, written explanation, models/APIs used and nominated social-post
links. It does not list a GitHub repository as mandatory. Follow any additional
required field shown in the actual final form. The official page states that
the submission form is sent by email and that a public demo post must be live
before submission. It also requires authentic engagement and synthetic demo
scenarios. Tag Gnani AI and include both required hashtags.
