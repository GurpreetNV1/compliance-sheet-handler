import os
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from difflib import SequenceMatcher

load_dotenv()

EMAIL = os.getenv("AGENTCIS_EMAIL")
PASSWORD = os.getenv("AGENTCIS_PASSWORD")


STATE_FILE = "agentcis_state.json"

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

        for i in range(count):

            link = links.nth(i)
            title = link.get_attribute("title")

            if not title:
                continue

            title_lower = title.lower()

            title_subclass = extract_subclass(title_lower)
            title_subsequent = "subsequent" in title_lower

            score = 0

            # =========================
            # 1️⃣ SUBCLASS MATCH (CRITICAL)
            # =========================
            if search_subclass and title_subclass:

                if search_subclass == title_subclass:
                    score += 1000   # highest priority
                else:
                    score -= 500    # strong penalty

            # =========================
            # 2️⃣ SUBSEQUENT ENTRANT MATCH
            # =========================
            if search_subsequent == title_subsequent:
                score += 200
            else:
                score -= 100

            # =========================
            # 3️⃣ FULL PHRASE
            # =========================
            if search in title_lower:
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

            # print(f"Checking → {title} | score={round(score,2)}")

            if score > best_score:
                best_score = score
                best_link = link
                best_title = title

        if best_link:
            print(f"✅ Selected Application → {best_title}")
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

    def fetch(self, phone, application_name):

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

        print(f"Searching for application: {application_name}")
        self.click_best_matching_application(application_name)

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

        page.wait_for_timeout(1000)

        rows_locator = page.locator(
            "div.ag-flex.ag-align-center.ag-space-between.col-v-3"
        )

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
            print("Checklist section not found → No documents uploaded")

        # print("\nChecklist Result:")
        for key, value in checklist_status.items():
            print(f"{key}: {value}")

        if "NO" in checklist_status.values():
            print("\n⚠ Missing documents detected")
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

