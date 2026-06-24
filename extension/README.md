# Chrome Extension

Load this folder as an unpacked Chrome extension:

```text
D:\codex\boss_zhipin\informationcatch\extension
```

Steps:

1. Open `chrome://extensions`
2. Enable `Developer mode`
3. Click `Load unpacked`
4. Select this `extension` folder
5. Reload the unpacked extension after any code change, especially after permission updates

Collection usage:

1. Start the local desktop app first
2. Confirm the local API endpoint in the popup
3. Open Boss or Liepin in a normal Chrome tab and log in manually
   - Boss recommended talent page
   - Liepin recommended page: `https://lpt.liepin.com/recommend`
4. Open the extension popup
5. Check `Job Title` and `Local API Base`
6. Click `Collect Current Page` or `Auto Scroll + Collect`

One-click automation usage:

1. Save a screening profile and AI settings in the desktop app's `Automation Flow` page
2. Keep the desktop app running
3. Open the Boss or Liepin recommendation page
4. Click `AUTO: Scroll + Collect + AI Screen` in the extension popup
5. The extension confirms the desktop workflow, auto-scrolls, imports the cards, and submits that batch for AI screening

Single chat usage:

1. Open a Boss chat page and select a candidate conversation
2. Open the extension popup
3. Fill `Resume Request Message`, `Wait Seconds`, and `Poll Interval`
4. Use one of:
   - `Send Resume Request`
   - `Download Current PDF`
   - `Send And Wait Then Download`

Batch usage:

1. Stay on the current Boss chat list you want to process, for example `沟通中`
2. Open the extension popup
3. Set the request message and waiting parameters
4. Click one of:
   - `Start Batch Resume Request`
   - `Start Batch Download`
5. Batch resume request only processes conversations in the current list that are unread and do not already contain an attachment resume card
6. Batch download scans the current list conversation by conversation; whenever it finds one or more attachment resumes, it starts downloading them and continues scrolling
7. You can close the popup while the batch task keeps running; reopen the popup to check status or click `Stop Batch Task`

Notes:

- Attachment resumes are the only signal treated as "resume already sent". Online resumes do not cause a skip.
- Candidate card collection supports Boss and Liepin; chat, batch resume request, and PDF download automation are Boss-only.
- Batch resume request sends the custom message, clicks `求简历`, and auto-confirms the dialog. It does not wait in the same batch task for the candidate to reply with a file.
- PDF files are downloaded through Chrome into the default download directory under `BossResumes/`.
- Downloads are handled by the extension background service worker, not by the popup.
- The batch runner stays inside the currently open Boss chat tab and does not switch main tabs for you.
