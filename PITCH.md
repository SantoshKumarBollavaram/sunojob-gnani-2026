# SunoJob
## From spoken requests to a shared work record.

Santosh Kumar Bollavaram | PES University | Solo project

### The problem

Customers and small service businesses often discuss work through voice.
A request can include a task, a changing quantity, something to avoid and
something that needs permission. For example: "Prepare fifty, actually forty
lunch boxes. Don't add onion. Ask me before changing the menu." Missing any
one of those details can leave the two sides expecting different work.

### The gap I focused on

A transcript preserves what was said, but someone still has to work out which
instructions apply now. A summary also needs to be checked: "ask before
changing the menu" is a condition, not permission to change it. When a customer
later changes the quantity, both sides need to review the revised instructions.

I focused on the step between understanding a conversation and agreeing on
the work: making the current interpretation clear, correctable and tied to
the version each person accepted.

### How SunoJob addresses it

The customer speaks in English or Telugu. Gnani Prisma transcribes the request,
and Gemini extracts a draft card with tasks, quantities, restrictions and
conditions linked to the original wording. Gnani Timbre reads it aloud so the
customer can catch a mistake before confirming.

A correction creates a revised version that needs fresh review. The service
provider then accepts that same version separately. Both sides can download
or receive an emailed record of the instructions and approvals. Earlier
approved records remain available when the request changes again.

I use Python, FastAPI and SQLite for the application. Validation checks source
references and correction consistency, while people remain responsible for
checking the meaning. The intended benefit is fewer misunderstandings before
work starts; that benefit still needs to be measured with users.

### Current stage and next step

The local prototype passes 236 offline software tests. I have manually checked
English and Telugu examples and receipt delivery to two test inboxes. These
checks do not establish general speech accuracy or customer demand.

Catering is the demonstration scenario. My next step is to test unfamiliar
speakers and a small service business, checking whether restrictions survive
corrections and whether both parties can complete the review without help.
