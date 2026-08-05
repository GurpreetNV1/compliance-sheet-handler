from typing import List, Dict
import copy

from collections import defaultdict


class BusinessRulesEngine:

    def __init__(self):
        pass

    # main

    
    
    
    def _drop_noise_skills_duplicates(self, docs):
        # Skills Assessment doc-type detection is often subject-driven (the
        # same subject is shared by every attachment of one email), so an
        # unrelated PDF attached alongside a real trigger email (e.g. a
        # generic government form attached to a CA ANZ request-info email)
        # can independently satisfy the same subject-based trigger and
        # produce a second, essentially blank "skills_*" doc for the same
        # email — confirmed live during Phase 4b testing. Within one email's
        # batch, if multiple docs share a document_type and at least one of
        # them actually carries identifying info (a reference, a name, or an
        # outcome), the empty sibling(s) are dropped as noise. A doc_type
        # with only one instance, or where every instance is empty (e.g. a
        # real AITSL notification that legitimately has neither), is left
        # untouched — this only removes duplicates, never a case's only doc.
        by_type = defaultdict(list)
        others = []

        for doc in docs:
            dtype = doc.get("document_type") or ""
            if dtype.startswith("skills_"):
                by_type[dtype].append(doc)
            else:
                others.append(doc)

        def is_informative(d):
            return bool(
                d.get("transaction_reference_number")
                or d.get("name")
                or (d.get("primary_applicant") or {}).get("name")
                or d.get("outcome")
            )

        result = list(others)
        for dtype, group in by_type.items():
            if len(group) == 1:
                result.extend(group)
                continue
            informative = [d for d in group if is_informative(d)]
            result.extend(informative if informative else group)

        return result

    def _group_by_trn(self, docs):

        groups = defaultdict(list)

        for doc in docs:

            trn = doc.get("transaction_reference_number") or "NO_TRN"

            groups[trn].append(doc)

        return list(groups.values())


    def _merge_group(self, doc_group):

    # ✅ If only one document — return as is
        if len(doc_group) == 1:
            return copy.deepcopy(doc_group[0])

        # --------------------------------------------------
        # STEP 1 — Find document with MAX applicants
        # --------------------------------------------------

        best_doc = None
        max_count = -1

        for doc in doc_group:

            count = 0

            if "primary_applicant" in doc:
                if doc.get("primary_applicant", {}).get("name"):
                    count += 1

                count += len(doc.get("secondary_applicants") or [])

            elif doc.get("name"):
                count += 1

            if count > max_count:
                max_count = count
                best_doc = doc

        base = copy.deepcopy(best_doc)

        # A real AQATO Positive outcome was found live where the covering
        # email's actual determination ("successfully completing a Skills
        # Assessment...") only exists in the email body, while the one PDF
        # attached that day was a secondary "Qualifications" document with
        # no outcome wording at all — both share the same reference number,
        # both name the same single applicant, so the applicant-count logic
        # above picked whichever came first, silently losing a real
        # Positive/Negative/Cancelled determination whenever it landed on
        # the other doc. Borrowed here rather than in the selection step
        # above so every other document_type's existing behavior is
        # untouched.
        if base.get("document_type") == "skills_outcome" and not base.get("outcome"):
            for doc in doc_group:
                if doc.get("outcome"):
                    base["outcome"] = doc.get("outcome")
                    base["outcome_date"] = doc.get("outcome_date") or base.get("outcome_date")
                    base["occupation"] = doc.get("occupation") or base.get("occupation")
                    if doc.get("validity_years"):
                        base["validity_years"] = doc.get("validity_years")
                    break

        # --------------------------------------------------
        # STEP 2 — If already multi applicants → done
        # --------------------------------------------------

        if base.get("secondary_applicants"):
            return base

        # --------------------------------------------------
        # STEP 3 — Otherwise merge names from all docs
        # --------------------------------------------------

        all_names = []

        for doc in doc_group:

            if "primary_applicant" in doc:

                primary = doc.get("primary_applicant") or {}

                if primary.get("name"):
                    all_names.append(primary["name"])

            elif doc.get("name"):
                all_names.append(doc.get("name"))

        # Remove duplicates
        seen = set()
        unique_names = []

        for n in all_names:
            if n and n not in seen:
                unique_names.append(n)
                seen.add(n)

        if not unique_names:
            return base

        # Inject back
        if "primary_applicant" in base:

            base["primary_applicant"]["name"] = unique_names[0]

            base["secondary_applicants"] = [
                {"name": n}
                for n in unique_names[1:]
            ]

        else:

            base["name"] = unique_names[0]

            base["secondary_applicants"] = [
                {"name": n}
                for n in unique_names[1:]
            ]

        return base



    def decide_entries(self, extracted_docs: List[Dict]) -> List[Dict]:
        # Decide final sheet entries from extracted documents.
        # Returns list of payloads to write to sheets.

        if not extracted_docs:
            return []

        extracted_docs = self._drop_noise_skills_duplicates(extracted_docs)

        checklist_docs = [
            d for d in extracted_docs
            if d.get("document_type") == "checklist"
        ]

        # Priority detection

        acknowledgements = [
            d for d in extracted_docs
            if d.get("document_type") == "acknowledgement"
        ]

        s56_docs = [
            d for d in extracted_docs
            if d.get("document_type") == "s56"
        ]

        grant_docs = [
            d for d in extracted_docs
            if d.get("document_type") == "grant"
        ]

        selected_docs = []

        # RULE 1 — Lodgement Priority
        if acknowledgements:
            print("Using acknowledgement documents")
            selected_docs = acknowledgements

        # RULE 2 — S56 Priority
        elif s56_docs:
            print("Using S56 documents")
            return self._process_s56(s56_docs, checklist_docs)

        # RULE 3 — Grant Logic
        elif grant_docs:
            print("Processing grant documents")
            return self._process_grants(grant_docs)

        # OTHER DOC TYPES
        else:
            print("Using other documents")
            selected_docs = extracted_docs

        # NEW — GROUP BY TRN

        grouped = self._group_by_trn(selected_docs)

        final_payloads = []

        for group in grouped:

            merged_doc = self._merge_group(group)

            final_payloads.append(
                self._create_payload(merged_doc)
            )

        return final_payloads



  # Payload

    def _create_payload(self, doc: Dict, checklist: Dict = None) -> Dict:

        payload = {
            "document_type": doc.get("document_type"),
            "document": doc
        }

        if checklist:
            payload["checklist"] = checklist

        return payload


    # S56

    def _process_s56(self, s56_docs: List[Dict], checklist_docs: List[Dict]) -> List[Dict]:

        payloads = []

        # Group S56 by TRN
        s56_groups = self._group_by_trn(s56_docs)

        for group in s56_groups:

            merged_s56 = self._merge_group(group)

            trn = merged_s56.get("transaction_reference_number")

            matched_checklist = None

            # Try match checklist by applicant name
            if checklist_docs:

                for chk in checklist_docs:

                    applicants = chk.get("applicants", [])

                    if not applicants:
                        continue

                    # compare first applicant name with primary
                    chk_name = applicants[0].get("name", "").lower()

                    primary = merged_s56.get("primary_applicant", {})
                    s56_name = (primary.get("name") or "").lower()

                    if chk_name and chk_name in s56_name:
                        matched_checklist = chk
                        break

            payloads.append(
                self._create_payload(
                    merged_s56,
                    checklist=matched_checklist
                )
            )

        return payloads


    def _process_grants(self, grant_docs: List[Dict]) -> List[Dict]:

        if len(grant_docs) == 1:
            return [self._create_payload(grant_docs[0])]

        # Detect visitor visa
        visa_text = (grant_docs[0].get("visa_program") or "").lower()

        is_visitor = "visitor" in visa_text

        if is_visitor:
            print("Visitor visa detected -> multiple entries")

            return [
                self._create_payload(doc)
                for doc in grant_docs
            ]

        # Non visitor → single combined entry
        print("Non-visitor multiple grants -> single entry")

        combined_names = []
        combined_trn = []

        base_doc = grant_docs[0].copy()

        for doc in grant_docs:

            primary = doc.get("primary_applicant", {}) or {}
            name = primary.get("name")

            if name and name not in combined_names:
                combined_names.append(name)

            trn = doc.get("transaction_reference_number")

            # ✅ prevent duplicate TRN
            if trn and trn not in combined_trn:
                combined_trn.append(trn)

        # Merge into base doc
        if combined_names:
            base_doc["primary_applicant"]["name"] = "\n".join(combined_names)

        # Usually only one TRN after grouping, but safe anyway
        base_doc["transaction_reference_number"] = ", ".join(combined_trn)

        return [self._create_payload(base_doc)]