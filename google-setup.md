# Google Gmail Setup

This project currently reads mail through IMAP. If you want to move the mailbox layer to Google Cloud Console / Gmail API later, use this setup as the starting point.

## What To Create In Google Cloud

1. Create or pick a Google Cloud project.
2. Enable the **Gmail API** for that project.
3. Configure the **OAuth consent screen**.
4. Create an **OAuth client ID**.
5. Use a **Desktop app** client if you are running this locally from Python.

## Recommended OAuth Scopes

For this project, start with read-only access unless you later need write actions:

- `https://www.googleapis.com/auth/gmail.readonly`

If you eventually need to label or modify messages, use a broader scope only when required.

## Local Files You Will Need

Place the downloaded OAuth client file in the project root and name it something like:

- `credentials.json`

You will also need a token cache file after the first login, typically:

- `token.json`

## Python Packages You Will Likely Need

If you replace IMAP with Gmail API, the mailbox layer will need Google client libraries. The usual set is:

- `google-api-python-client`
- `google-auth`
- `google-auth-oauthlib`
- `google-auth-httplib2`

## Expected Flow

1. User authorizes the app in a browser.
2. App receives OAuth tokens.
3. App lists Gmail messages using the API.
4. App fetches message details and attachments.
5. App passes the same email metadata into the existing pipeline:
   - attachment extraction
   - business rules
   - Agentcis lookup
   - Excel write

## What You Will Need To Change In Code Later

If you switch from IMAP to Gmail API, the main replacement will be the mailbox reader currently in:

- `imap_handler/imap_client.py`

The rest of the pipeline can stay mostly the same if you keep returning a similar email metadata shape:

- `subject`
- `date`
- `recipients`
- `cc`
- `attachments`
- `folder_path`

## Useful Gmail API Capabilities

The Gmail API is a better fit than IMAP if you want:

- message listing with structured metadata
- thread-aware handling
- reliable `internalDate`
- push notifications via Gmail watch + Pub/Sub
- easier long-term sync logic

## Practical Note

If you only change the Gmail access method but keep the same date-filter logic, you will still have the same “which email in a thread should be processed” problem. The API helps, but the selection logic still needs to be designed properly.

## Gmail API Migration Checklist For This Project

Use this order if you decide to replace IMAP later:

1. Add Google auth libraries to `requirements.txt`.
2. Create `credentials.json` from Google Cloud Console and place it in the project root.
3. Implement OAuth token storage and refresh handling in a new Gmail client module.
4. Replace `imap_handler/imap_client.py` with Gmail API calls.
5. Keep the same return shape for email metadata so the rest of the pipeline stays stable.
6. Map Gmail message IDs or thread IDs to a local processed-state file so reprocessing is controlled.
7. Fetch attachments from Gmail message payload parts and save them under `storage/` exactly as the current code expects.
8. Preserve these fields in the email object returned to the orchestrator:
   - `message_id`
   - `subject`
   - `date`
   - `recipients`
   - `cc`
   - `attachments`
   - `folder_path`
   - `thread_id` if you want thread-aware logic
9. Reuse the existing pipeline:
   - `attachment_reader.processor.AttachmentProcessor`
   - `core.business_rules.BusinessRulesEngine`
   - `core.field_mapper.FieldMapper`
   - `sheets.sheets_handler.write_to_excel`
   - `agentcis.agentcis_handler.AgentcisSession`
10. Decide how you want to process replies:
    - by message date only
    - by thread ID
    - by thread ID plus latest message only

## Suggested Behavior For Replies

For your workflow, the safest Gmail API design is usually:

- fetch messages in a date window
- group by `threadId`
- inspect the latest message in the thread
- optionally include earlier thread messages if the attachment or subject indicates they belong to the same case

That is better than treating each message as fully independent when you expect follow-up emails like:

- lodgement first
- bridging visa or s56 later

## Minimal Migration Target

If you want the smallest possible change, build a Gmail client that returns the same shape as the current IMAP client and only swap the implementation underneath. That lets the existing orchestrator continue working with minimal edits.
