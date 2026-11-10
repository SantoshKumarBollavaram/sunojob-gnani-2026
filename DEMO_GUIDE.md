# Record the working application

Use the existing application in `$HOME/sunojob`, which contains your saved
requests. This submission folder is a clean source copy; it deliberately has
no copies of those requests or your email delivery records.

## Start

```bash
cd "$HOME/sunojob"
.venv/bin/python -m sunojob.serve --model gemini-3.5-flash-lite --email
```

Complete the hidden-key and SMTP prompts before recording. For Gmail: host
`smtp.gmail.com`, port `587`, mode `starttls`, full sender email as username,
and the Google App Password belonging to that sender account. Keep this
terminal out of the public recording. Open http://127.0.0.1:8765.

## Record one complete fresh flow

Use synthetic work details and your own consented voice. Keep each request
recording under 25 seconds. Do not use real customer recordings or identifiers.

1. Choose English and start a new request.
2. Record: “Prepare fifty, actually forty lunch boxes. Do not add onion. Ask
   me before changing the menu.”
3. Verify the draft: 40, onion excluded, and permission required before menu
   changes. If the interpretation differs, show and resolve it; do not claim
   an incorrect draft passed.
4. Generate the spoken readback and play it fully. Capture its sound.
5. Record: “Make that forty-five lunch boxes. Keep the other instructions.”
6. Show the revised quantity 45 and both restrictions. Generate and fully
   listen to the updated readback, then record “I confirm.”
7. Create and open the owner review link on this laptop. Review and accept
   the same version using a fictional demo display name. In narration, state
   that you are acting as both roles for the demonstration.
8. Download the shared HTML record and show the current instructions, both
   approval records, correction history and readable IST times.
9. If demonstrating delivery, use intended inboxes you control. Preview the
   recipients, explicitly send once, and check both real inboxes. Keep email
   addresses off-screen or blur them in the published video. Label SMTP
   acceptance accurately; do not call it inbox delivery until checked.
10. Refresh and show the saved state. Do not record another correction after
    the final approval just to keep the microphone active.

## Telugu example

In a separate fresh request choose Telugu + English and record:

> యాభై కాదు, నలభై భోజన పెట్టెలు సిద్ధం చేయండి. ఉల్లిపాయ వేయవద్దు. మెనూ మార్చే ముందు నన్ను అడగండి.

Expected interpretation: 40 lunch boxes, no onion, ask before changing the
menu. Then correct:

> నలభై ఐదు భోజన పెట్టెలు చేయండి.

Expected: 45 with both restrictions retained. Play the new readback fully
and confirm with “అవును”, then finish separate owner acceptance. Do not
claim broader language performance based on this scripted example.

## Public video structure

Prioritize a clear complete working demo within the form's actual length/file
limit. A 60-second edit is optional and fits the published 60-second demo award;
it is not a general length requirement for every submission.

| Segment | Show | Suggested narration |
| --- | --- | --- |
| Opening | App and request | “SunoJob helps customers and service businesses review what was actually requested before work begins.” |
| Speech | A real recording and resulting card | “Gnani Prisma transcribes the request. Gemini structures the draft, including restrictions and corrections.” |
| Readback | Timbre audio playing | “Gnani Timbre reads back the current instructions so the customer can catch a mistake.” |
| Correction | Revised card and approval reset | “Changing the quantity preserves the restrictions and requires fresh review.” |
| Acceptance | Separate owner page and receipt | “Both roles accept the same version, then receive the shared record. I am demonstrating both roles here.” |
| Closing | Receipt and local prototype label | “This local English/Telugu prototype has 236 passing offline tests. Independent real-world speech evaluation is still pending.” |

Screen-record using Ubuntu's recorder (`Ctrl+Alt+Shift+R`) or an existing
recorder you know. Check the audio source first. If installing OBS is necessary:

```bash
sudo apt-get update
sudo apt-get install -y obs-studio
obs
```

In OBS add a screen/window source, microphone and desktop audio. Make a short
test, listen to it, then record. Hide notifications, API/SMTP setup and personal
inbox details. Editing out wait time is fine if it does not imply measured
real-time latency; label shortened waits. Do not show offline fixtures as live
Gnani inference. Upload the working video directly to LinkedIn/X with the post.

## Recording checks before posting

- Readable text and audible speech/readback.
- Correct quantity and restrictions in the final approved version.
- Real Gnani calls, with keys and passwords hidden.
- No personal identifiers, private review tokens or inbox contents exposed.
- No fabricated users, performance metrics or customer validation.
- Video accessible to the intended public audience after posting.
