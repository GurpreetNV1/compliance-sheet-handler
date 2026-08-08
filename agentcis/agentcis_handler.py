import json
import os
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from difflib import SequenceMatcher

load_dotenv()

EMAIL = os.getenv("AGENTCIS_EMAIL")
PASSWORD = os.getenv("AGENTCIS_PASSWORD")


STATE_FILE = "agentcis_state.json"

# Maps a Skills Assessment authority to the provider/organization text
# Agentcis shows under an application's title (e.g. "EA Skills Assessment
# \n\n Engineers Australia (Head Office)"). Used to pick the RIGHT
# application out of a client's full list when there's no application name
# to search with — confirmed live that a client can have several
# applications (an old VETASSESS case, a visa case, an EA Skills case, …)
# and blindly clicking "the first row" picks whichever happens to be listed
# first, not the one the email is actually about (real case: client 9282's
# first-listed application was a completed, unrelated VETASSESS case from
# 2024 — the real EA Skills Assessment application was listed last).
_AUTHORITY_PROVIDER_HINTS = {
    "VETASSESS": ["vetassess"],
    "EA": ["engineers australia"],
    "TRA": ["trades recognition australia"],
    "ACECQA": ["acecqa"],
    "ACS": ["australian computer society"],
    "AIQS": ["australian institute of quantity surveyors"],
    "AITSL": ["aitsl", "australian institute for teaching"],
    "ANMAC": ["anmac"],
    "AQATO": ["aqato", "australian trade training college"],
    "CA ANZ": ["chartered accountants"],
}

TEST_CASES = [
("asma.shaikh74@gmail.com", "Vetassess"),
("carwhisperer@carwhisperer.com.au", "186"),
("426578700", "Subsequent Entrant"),
]

def extract_subclass(text):
    if not text:
        return None

    match = re.search(r"\b(\d{3})\b", text)
    return match.group(1) if match else None



def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def find_invoice_for_application(invoices, application_id):
    if not application_id:
        return None

    application_id = str(application_id).strip()

    for invoice in invoices:
        if str(invoice.get("application_id")).strip() == application_id:
            return invoice

    return None

class AgentcisSession:


    def __init__(self):

        self.playwright = sync_playwright().start()

        self.browser = self.playwright.chromium.launch(
            headless=False,  # Visible browser for testing
            slow_mo=50
        )

        # Load saved login session if exists
        if os.path.exists(STATE_FILE):
            print("Loading saved session...")
            self.context = self.browser.new_context(storage_state=STATE_FILE)
        else:
            print("No saved session found — fresh login required")
            self.context = self.browser.new_context()

        self.page = self.context.new_page()

# ---------------- LOGIN ---------------- #

    def login(self):

        print("Logging into Agentcis...")

        self.page.goto(
            "https://acmemigration.agentcisapp.com/",
            wait_until="domcontentloaded"
        )

        # If already logged in → skip
        if "overview" in self.page.url:
            print("Already logged in (session valid)")
            return

        self.page.fill('input[name="email"]', EMAIL)
        self.page.fill('input[name="password"]', PASSWORD)
        self.page.click('button[type="submit"]')

        self.page.wait_for_url("**/overview")

        print("Login Successful")

        # Save session
        self.context.storage_state(path=STATE_FILE)
        print("Session saved")

    def ensure_logged_in(self):

        self.page.goto(
            "https://acmemigration.agentcisapp.com/overview",
            wait_until="domcontentloaded"
        )

        # Case 1 — redirected to login page
        if "login" in self.page.url.lower():
            print("Session expired — logging in again")
            self.login()
            return

        # Case 2 — session popup modal
        self.handle_session_popup()

    # ---------------- APPLICATION SEARCH ---------------- #

    def click_best_matching_application(self, application_name):

        print("Finding best matching application...")

        self.page.wait_for_function(
            "() => document.querySelectorAll('tbody a[title]').length > 0"
        )

        links = self.page.locator("tbody a[title]")
        count = links.count()

        search = (application_name or "").lower().strip()

        if not search:
            raise Exception("Application name empty — cannot match")

        search_subclass = extract_subclass(search)
        search_subsequent = "subsequent" in search

        best_link = None
        best_score = -1
        best_title = None
        best_is_relevant = False
        subclass_matched_any = False

        for i in range(count):

            link = links.nth(i)
            title = link.get_attribute("title")

            if not title:
                continue

            title_lower = title.lower()

            title_subclass = extract_subclass(title_lower)
            title_subsequent = "subsequent" in title_lower

            score = 0
            subclass_match = False

            # =========================
            # 1️⃣ SUBCLASS MATCH (CRITICAL)
            # =========================
            if search_subclass and title_subclass:

                if search_subclass == title_subclass:
                    score += 1000   # highest priority
                    subclass_match = True
                    subclass_matched_any = True
                else:
                    score -= 500    # strong penalty

            # =========================
            # 2️⃣ SUBSEQUENT ENTRANT MATCH
            # =========================
            # Deliberately NOT counted toward "is this candidate even
            # relevant" below — it's a boolean coincidence (neither being a
            # "subsequent entrant" variant) that two completely unrelated
            # applications can share for free, with no bearing on whether
            # they're actually the same case.
            if search_subsequent == title_subsequent:
                score += 200
            else:
                score -= 100

            # =========================
            # 3️⃣ FULL PHRASE
            # =========================
            full_phrase_match = search in title_lower
            if full_phrase_match:
                score += 100

            # =========================
            # 4️⃣ WORD MATCH
            # =========================
            tokens = search.split()
            word_hits = sum(1 for t in tokens if t in title_lower)
            score += word_hits * 20

            # =========================
            # 5️⃣ SIMILARITY
            # =========================
            score += similarity(search, title_lower) * 50

            # A candidate only counts as genuinely relevant — as opposed to
            # merely not being penalized — if it has an actual point of
            # contact with the search term: a matching subclass, the full
            # search phrase, or at least one shared word. Without this,
            # "best score" can still be a completely unrelated application
            # that only won by not losing (e.g. a Skills Assessment/JRP
            # record picked for a visa subclass the client doesn't have in
            # Agentcis yet — real case this was found from).
            is_relevant = subclass_match or full_phrase_match or word_hits > 0

            # print(f"Checking → {title} | score={round(score,2)} | relevant={is_relevant}")

            if score > best_score:
                best_score = score
                best_link = link
                best_title = title
                best_is_relevant = is_relevant

        # Same "blank over wrong guess" rule already applied to Agentcis
        # name-search elsewhere — refuse rather than click through to an
        # application with no genuine relevance to what was searched for.
        if best_link and not best_is_relevant:
            raise Exception(
                f"No genuinely relevant application found for: {application_name} "
                f"(best fuzzy match was {best_title!r}, score={best_score:.1f} — "
                f"rejected rather than guessed, no shared subclass/phrase/word)"
            )

        if search_subclass and not subclass_matched_any:
            raise Exception(
                f"No application with subclass {search_subclass} found for: {application_name} "
                f"(best fuzzy match was {best_title!r} — rejected rather than guessed)"
            )

        if best_link:
            print(f"Selected Application -> {best_title}")
            best_link.click()
            return

        raise Exception(f"No similar application found for: {application_name}")


    # 
    def handle_session_popup(self):
        password_box = self.page.locator('input[name="password"]')

        if password_box.count() > 0 and password_box.is_visible():
            print("Session popup detected — re-authenticating...")

            password_box.fill(PASSWORD)

            self.page.locator('button:has-text("Login")').click()

            # Wait until popup disappears / dashboard usable
            self.page.wait_for_timeout(2000)

            # Save session again
            self.context.storage_state(path=STATE_FILE)

            print("Session restored")

    # ---------------- MAIN FETCH ---------------- #

    def fetch(self, phone, application_name, authority=None):

        self.ensure_logged_in()
        self.handle_session_popup()

        print("\n==============================")
        print("Processing:", phone, "|", application_name)
        print("==============================")

        page = self.page

        page.click(".ag-search__button")
        page.wait_for_selector(".ag-search__input")

        page.fill(".ag-search__input", "")
        page.type(".ag-search__input", phone, delay=150)
        page.wait_for_timeout(2500)

        page.locator('.ag-menu--shown a[href*="/contacts/u/"]').first.click()
        page.wait_for_url("**/contacts/u/**")

        return self._extract_client_and_application(application_name, authority=authority)

    # ---------------- DIRECT CLIENT ID FETCH ---------------- #
    #
    # For Skills Assessment cases (VETASSESS/EA/ACECQA/ACS/AIQS/AITSL/ANMAC/
    # AQATO/CA ANZ), a real client email is only reliably present for TRA —
    # every other authority's correspondence is internal-only, and searching
    # Agentcis by name is too risky (common names return many unrelated
    # contacts). Once a case's Client ID is already known (recorded on an
    # earlier row in the Lodgement tab), this opens that contact directly by
    # URL — no search, no name-ambiguity risk at all.
    def fetch_by_client_id(self, client_id, application_name="", authority=None):

        self.ensure_logged_in()
        self.handle_session_popup()

        print("\n==============================")
        print("Processing (direct Client ID):", client_id, "|", application_name)
        print("==============================")

        page = self.page

        page.goto(
            f"https://acmemigration.agentcisapp.com/app#/contacts/u/{client_id}/activities",
            wait_until="domcontentloaded",
        )
        page.wait_for_url("**/contacts/u/**")

        return self._extract_client_and_application(application_name, authority=authority)

    # ---------------- SHARED: client page -> application details ---------------- #
    #
    # Used by both fetch() (search-based) and fetch_by_client_id() (direct)
    # once the browser is already sitting on a contact's page.
    def _extract_client_and_application(self, application_name, authority=None):

        page = self.page

        # print("Client Page Opened")

        page.wait_for_selector(".ag-client__title")

        client_name = page.locator(".ag-client__title").inner_text().strip()
        print("Client Name:", client_name)

        internal_id = page.evaluate("""
        () => {
            let internalId = 'N/A';
            const labels = Array.from(document.querySelectorAll('label'));
            const internalLabel = labels.find(l =>
                l.innerText.replace(/\\s+/g, ' ').includes('Internal Id')
            );
            if (internalLabel) {
                const row = internalLabel.closest('div[style*="margin-bottom"]');
                internalId =
                    row?.querySelector('span')?.innerText?.trim() || 'N/A';
            }
            return internalId;
        }
        """)

        print("Internal ID:", internal_id)

        # print("Navigating to Applications tab...")
        page.click("ul.nav-tabs a:has-text('Applications')")
        page.wait_for_selector("tbody tr", timeout=20000)

        # print("Applications tab fully loaded")

        empty_checklist = {doc: "NO" for doc in [
            "Client Agreement",
            "Proof of Invoice Payment (Paid/Partially Paid)",
            "Form 956",
        ]}

        if (application_name or "").strip():
            print(f"Searching for application: {application_name}")
            self.click_best_matching_application(application_name)
        else:
            # Several Skills Assessment doc types have no visa/application
            # name to search with at all — that's a legitimate absence, not
            # a bug. Previously this just reported every document as "NO"
            # regardless of the client's real state, which is what produced
            # the 956/Client Agreement/Payment inconsistencies flagged live —
            # opening whichever application appears first (assumed most
            # recent) instead reports that application's real status rather
            # than a blanket guess. If the client genuinely has none on
            # file, that's reported as-is below.
            print("No application name to search — using client's most recent application for document status")
            # The table renders loading-placeholder <tr>s before the real
            # rows arrive, so "tbody tr" is satisfied instantly and a count
            # taken right away always reads 0 — a real client's real
            # application was being missed this way (confirmed live: client
            # 14429 has a genuine application on file, but the immediate
            # count reported none). Wait for the placeholders to clear
            # (whether they resolve into real rows or a genuine empty state)
            # before counting.
            try:
                page.wait_for_function(
                    "() => document.querySelectorAll('tbody .content-placeholder-text').length === 0",
                    timeout=10000,
                )
            except PlaywrightTimeoutError:
                pass
            application_rows = page.locator("tbody a[title]")
            row_count = application_rows.count()
            if row_count == 0:
                print("Client has no applications on file")
                return {
                    "clientName": client_name,
                    "internalId": internal_id,
                    "applicationId": "",
                    "assignee": "N/A",
                    "applicationStatus": "N/A",
                    "currentStage": "N/A",
                    "checklist": empty_checklist,
                }

            hints = _AUTHORITY_PROVIDER_HINTS.get(authority)
            matched_row = None
            if hints:
                table_rows = page.locator("tbody tr")
                for i in range(table_rows.count()):
                    row_text = table_rows.nth(i).inner_text().lower()
                    if any(h in row_text for h in hints):
                        matched_row = table_rows.nth(i).locator("a[title]").first
                        break

            if hints and matched_row is None:
                # The client has applications, but none for this specific
                # authority — clicking the wrong one (e.g. an unrelated
                # visa case) would report that case's checklist/stage as if
                # it belonged to this Skills case. Blank is safer than a
                # wrong guess, same rule used everywhere else in this
                # pipeline.
                print(f"Client has applications, but none matching authority {authority!r} — reporting blank rather than guessing")
                return {
                    "clientName": client_name,
                    "internalId": internal_id,
                    "applicationId": "",
                    "assignee": "N/A",
                    "applicationStatus": "N/A",
                    "currentStage": "N/A",
                    "checklist": empty_checklist,
                }

            (matched_row or application_rows.first).click()

        page.wait_for_selector(".ui.five.column.grid", timeout=20000)

        # print("Application page opened successfully")

        application_id = page.url.rstrip("/").split("/")[-1]
        # print("Application ID:", application_id)

        try:
            page.wait_for_selector("span.ag-application__status", timeout=15000)
            application_status = page.locator(
                "span.ag-application__status"
            ).first.inner_text().strip()
        except:
            application_status = "N/A"

        # print("Application Status:", application_status)

        try:
            stage_column = page.locator(
                "div.ui.five.column.grid div.column",
                has=page.locator("span:text('Current Stage')")
            ).first

            current_stage = stage_column.locator("h5").inner_text().strip()
        except:
            current_stage = "N/A"

        # print("Current Stage:", current_stage)

        assignee = page.locator(".avatares span[title]").first.get_attribute("title") or "N/A"
        # print("Assignee:", assignee)

        # -------- DOCUMENTS -------- #

        # print("Opening Documents tab...")
        page.locator("li.ag-tab__menu", has_text="Documents").click()
        page.wait_for_selector("table.ag-table tbody tr", timeout=20000)

        # print("Checking individual checklist items...")

        documents_required = [
            "Client Agreement",
            "Proof of Invoice Payment (Paid/Partially Paid)",
            "Form 956"
        ]

        checklist_status = {doc: "NO" for doc in documents_required}

        # A fixed 1000ms sleep here isn't reliably enough for the checklist
        # rows to render after the Documents tab click — confirmed live
        # against client 14429's real application (17093, checklist fully
        # ticked), which still reported "not found" at 1000ms but appeared
        # by ~2500ms. Wait for the actual rows instead of guessing a delay.
        rows_locator = page.locator(
            "div.ag-flex.ag-align-center.ag-space-between.col-v-3"
        )
        try:
            rows_locator.first.wait_for(state="attached", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        if rows_locator.count() > 0:

            checklist_rows = rows_locator

            for i in range(checklist_rows.count()):

                row = checklist_rows.nth(i)
                name_locator = row.locator("div.text-semi-bold.fs-14")

                if name_locator.count() == 0:
                    continue

                name = name_locator.inner_text().strip()

                if name not in documents_required:
                    continue

                has_tick = row.locator("svg.check-icon").count() > 0
                checklist_status[name] = "YES" if has_tick else "NO"

        else:
            print("Checklist section not found -> No documents uploaded")

        # print("\nChecklist Result:")
        for key, value in checklist_status.items():
            print(f"{key}: {value}")

        if "NO" in checklist_status.values():
            print("\nMissing documents detected")
        else:
            print("\nAll checklist items completed")

        final_data = {
            "clientName": client_name,
            "internalId": internal_id,
            "applicationId": application_id,
            "assignee": assignee,
            "applicationStatus": application_status,
            "currentStage": current_stage,
            "checklist": checklist_status
        }

        # print("\nFINAL DATA:")
        # print(final_data)

        return final_data

    # ---------------- NAME-BASED FALLBACK FETCH ---------------- #
    #
    # Used when there's no usable client recipient to search by (confirmed live:
    # S57 is ~100% internal-only, ART ~97%, S64/Citizenship Appointment mixed).
    # Agentcis search DOES support name search, but common names return many
    # candidates with no reliable auto-disambiguation signal (verified live:
    # "Harmeet Singh" / "Akashdeep Singh" each returned 9 different contacts).
    # So this only proceeds when the search returns EXACTLY ONE contact —
    # anything ambiguous or empty is treated as no-match (caller writes the row
    # with blank Agentcis fields rather than risking a wrong guess).
    #
    # Deliberately NOT sharing code with fetch() above — fetch() is proven
    # working in production (phase 1) and is left untouched; this duplicates
    # the "open contact + extract data" portion rather than risk regressing it
    # via a shared-helper refactor.

    def fetch_by_name(self, name, application_name):

        self.ensure_logged_in()
        self.handle_session_popup()

        print("\n==============================")
        print("Processing (name search):", name, "|", application_name)
        print("==============================")

        page = self.page

        page.click(".ag-search__button")
        page.wait_for_selector(".ag-search__input")

        page.fill(".ag-search__input", "")
        page.type(".ag-search__input", name, delay=150)
        page.wait_for_timeout(2500)

        results = page.locator('.ag-menu--shown a[href*="/contacts/u/"]')
        count = results.count()

        if count != 1:
            print(f"Name search for '{name}' returned {count} candidate(s) — "
                  f"not unique, treating as no match")
            return None

        results.first.click()
        page.wait_for_url("**/contacts/u/**")

        page.wait_for_selector(".ag-client__title")

        client_name = page.locator(".ag-client__title").inner_text().strip()
        print("Client Name:", client_name)

        internal_id = page.evaluate("""
        () => {
            let internalId = 'N/A';
            const labels = Array.from(document.querySelectorAll('label'));
            const internalLabel = labels.find(l =>
                l.innerText.replace(/\\s+/g, ' ').includes('Internal Id')
            );
            if (internalLabel) {
                const row = internalLabel.closest('div[style*="margin-bottom"]');
                internalId =
                    row?.querySelector('span')?.innerText?.trim() || 'N/A';
            }
            return internalId;
        }
        """)

        print("Internal ID:", internal_id)

        page.click("ul.nav-tabs a:has-text('Applications')")
        page.wait_for_selector("tbody tr", timeout=20000)

        print(f"Searching for application: {application_name}")

        try:
            self.click_best_matching_application(application_name)
        except Exception as e:
            print(f"No matching application for '{name}': {e}")
            return None

        page.wait_for_selector(".ui.five.column.grid", timeout=20000)

        application_id = page.url.rstrip("/").split("/")[-1]

        try:
            page.wait_for_selector("span.ag-application__status", timeout=15000)
            application_status = page.locator(
                "span.ag-application__status"
            ).first.inner_text().strip()
        except:
            application_status = "N/A"

        try:
            stage_column = page.locator(
                "div.ui.five.column.grid div.column",
                has=page.locator("span:text('Current Stage')")
            ).first

            current_stage = stage_column.locator("h5").inner_text().strip()
        except:
            current_stage = "N/A"

        assignee = page.locator(".avatares span[title]").first.get_attribute("title") or "N/A"

        page.locator("li.ag-tab__menu", has_text="Documents").click()
        page.wait_for_selector("table.ag-table tbody tr", timeout=20000)

        documents_required = [
            "Client Agreement",
            "Proof of Invoice Payment (Paid/Partially Paid)",
            "Form 956"
        ]

        checklist_status = {doc: "NO" for doc in documents_required}

        # See _extract_client_and_application's identical checklist block —
        # a fixed 1000ms sleep isn't reliably enough for these rows to
        # render after the Documents tab click; wait for them directly.
        rows_locator = page.locator(
            "div.ag-flex.ag-align-center.ag-space-between.col-v-3"
        )
        try:
            rows_locator.first.wait_for(state="attached", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        if rows_locator.count() > 0:

            checklist_rows = rows_locator

            for i in range(checklist_rows.count()):

                row = checklist_rows.nth(i)
                name_locator = row.locator("div.text-semi-bold.fs-14")

                if name_locator.count() == 0:
                    continue

                doc_name = name_locator.inner_text().strip()

                if doc_name not in documents_required:
                    continue

                has_tick = row.locator("svg.check-icon").count() > 0
                checklist_status[doc_name] = "YES" if has_tick else "NO"

        final_data = {
            "clientName": client_name,
            "internalId": internal_id,
            "applicationId": application_id,
            "assignee": assignee,
            "applicationStatus": application_status,
            "currentStage": current_stage,
            "checklist": checklist_status
        }

        return final_data

    # ---------------- INVOICES / REVENUE ---------------- #
    #
    # This endpoint (/api/v2/clients/{id}/invoices) isn't part of Agentcis's
    # documented, token-authenticated API — calling it directly with the API
    # key returns 401 "session_expired" (confirmed live). It only accepts a
    # real logged-in browser session, so it's called from inside the page
    # itself (page.evaluate + fetch with credentials:"include"), reusing
    # this same authenticated Playwright session rather than a raw HTTP
    # request. Each invoice in the response already carries its own
    # application_id — no need to open individual invoices to find out
    # which application they belong to.
    def fetch_invoices(self, client_id, per_page=100):
        page = self.page

        result = page.evaluate(f"""
            async () => {{
                const res = await fetch(
                    "https://acmemigration.agentcisapp.com/api/v2/clients/{client_id}/invoices?per_page={per_page}&page=1",
                    {{ headers: {{ "Accept": "application/json" }}, credentials: "include" }}
                );
                return {{ status: res.status, body: await res.text() }};
            }}
        """)

        if result["status"] != 200:
            print(f"Failed to fetch invoices for client {client_id}: HTTP {result['status']}")
            return []

        try:
            data = json.loads(result["body"])
        except json.JSONDecodeError as e:
            print(f"Invoice response for client {client_id} was not valid JSON: {e}")
            return []

        return data.get("data", [])

    # ---------------- CLOSE ---------------- #

    def close(self):
        self.browser.close()
        self.playwright.stop()


# ================= RUN =================

if __name__== "__main__":


    if not EMAIL or not PASSWORD:
        print("Email or Password missing in .env file")
        exit()

    session = AgentcisSession()

    try:

        session.login()

        for phone, app in TEST_CASES:
            session.fetch(phone, app)

    finally:
        session.close()

