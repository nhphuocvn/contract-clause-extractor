"""Canonical text of the synthetic Warrant to Purchase Shares of Common Stock (Doc B).

Companion to `_doc_a_content.py`. Structurally modeled on warrants of the type
filed publicly as 8-K exhibits in connection with strategic supply transactions;
all numbers and party names are synthetic.

Section 1's grant ties to the cross-reference in Doc A §13. Sections 2–4 carry
the milestone-and-hurdle vesting logic that warrant_economics.py (Phase 4) will
consume. Section 8 (Confidentiality) is included specifically as a test case
for the extractor — it is boilerplate and should NOT be classified as a
commercial term.
"""

TITLE = "WARRANT TO PURCHASE SHARES OF COMMON STOCK"

NOTICE = (
    "SYNTHETIC — FICTIONAL — FOR DEMO USE ONLY. This document is a generated "
    "sample used to test the Deal Economics Copilot. The share counts, "
    "exercise price, milestones, and stock price hurdles set forth herein "
    "are illustrative and do not reflect the terms of any real warrant issued "
    "by any real party."
)

PREAMBLE = (
    "This Warrant to Purchase Shares of Common Stock (this “Warrant”) is "
    "issued as of February 1, 2026 (the “Issue Date”) by Advanced Micro "
    "Devices, Inc., a Delaware corporation (the “Company”), to Meta "
    "Platforms, Inc., a Delaware corporation (the “Holder”). This Warrant is "
    "issued in connection with, and pursuant to Section 13 of, that certain "
    "GPU Cloud Product Purchase Agreement of even date herewith by and "
    "between the Company and the Holder (the “Purchase Agreement”). "
    "Capitalized terms used but not defined herein shall have the meanings "
    "given to them in the Purchase Agreement."
)

# Each entry: (section_number, ALL_CAPS_TITLE, [paragraph1, paragraph2, ...])
SECTIONS: list[tuple[int, str, list[str]]] = [
    (1, "GRANT OF WARRANT", [
        "Subject to the terms and conditions of this Warrant, the Company "
        "hereby grants to the Holder the right to purchase from the Company, "
        "from time to time during the Exercise Period and in accordance with "
        "the vesting schedule set forth in Section 2, up to twelve million "
        "(12,000,000) fully paid and non-assessable shares of the Company’s "
        "common stock, par value $0.01 per share (the “Warrant Shares”), at "
        "an exercise price of one cent ($0.01) per Warrant Share (the "
        "“Exercise Price”).",

        "The Exercise Price and the number of Warrant Shares issuable upon "
        "exercise of this Warrant are subject to adjustment from time to "
        "time pursuant to Section 5. The Warrant Shares, when issued upon "
        "exercise of this Warrant in accordance with its terms, will be duly "
        "authorized, validly issued, fully paid, non-assessable, and free of "
        "preemptive rights, other than restrictions on transfer set forth in "
        "Section 6 and under applicable securities laws.",
    ]),

    (2, "VESTING SCHEDULE", [
        "This Warrant shall vest and become exercisable in four (4) equal "
        "tranches of three million (3,000,000) Warrant Shares each (each, a "
        "“Tranche”), upon the satisfaction of the cumulative deployment "
        "milestones set forth in this Section 2 and the stock price hurdles "
        "set forth in Section 3. For purposes of this Warrant, a Warrant "
        "Share shall be deemed to have “vested” only upon satisfaction of "
        "both the applicable deployment milestone and the applicable stock "
        "price hurdle.",

        "The Tranches and their corresponding cumulative deployment "
        "milestones are as follows: (i) the first Tranche, consisting of "
        "three million (3,000,000) Warrant Shares, shall be eligible to "
        "vest upon the Holder’s cumulative deployment of thirty thousand "
        "(30,000) GPU Units acquired pursuant to the Purchase Agreement "
        "(the “Tranche 1 Milestone”); (ii) the second Tranche, consisting "
        "of three million (3,000,000) Warrant Shares, shall be eligible to "
        "vest upon the Holder’s cumulative deployment of seventy-five "
        "thousand (75,000) GPU Units (the “Tranche 2 Milestone”); (iii) "
        "the third Tranche, consisting of three million (3,000,000) Warrant "
        "Shares, shall be eligible to vest upon the Holder’s cumulative "
        "deployment of one hundred twenty thousand (120,000) GPU Units (the "
        "“Tranche 3 Milestone”); and (iv) the fourth Tranche, consisting "
        "of three million (3,000,000) Warrant Shares, shall be eligible to "
        "vest upon the Holder’s cumulative deployment of one hundred fifty "
        "thousand (150,000) GPU Units (the “Tranche 4 Milestone”).",

        "For purposes of this Section 2, GPU Units shall be considered "
        "“deployed” when they have been installed and brought into "
        "productive use in Holder’s data center infrastructure, as certified "
        "by Holder in writing on a Quarterly basis. The Company shall be "
        "entitled to rely on Holder’s written certification of cumulative "
        "deployment for purposes of determining whether a deployment "
        "milestone has been satisfied.",
    ]),

    (3, "STOCK PRICE HURDLES", [
        "In addition to satisfaction of the applicable deployment "
        "milestone, each Tranche shall vest only if and when the volume "
        "weighted average price per share of the Company’s common stock, "
        "as reported on the principal national securities exchange on "
        "which such stock is listed, equals or exceeds the applicable "
        "stock price hurdle for such Tranche over any thirty (30) "
        "consecutive trading day period (each, a “VWAP Hurdle”).",

        "The VWAP Hurdles applicable to each Tranche are as follows: (i) "
        "one hundred eighty United States dollars ($180.00) per share for "
        "the first Tranche; (ii) two hundred thirty United States dollars "
        "($230.00) per share for the second Tranche; (iii) three hundred "
        "United States dollars ($300.00) per share for the third Tranche; "
        "and (iv) four hundred United States dollars ($400.00) per share "
        "for the fourth Tranche. The VWAP Hurdles shall be adjusted to "
        "reflect any stock split, reverse stock split, stock dividend, or "
        "similar event occurring after the Issue Date in the same manner "
        "as adjustments made under Section 5.",

        "A Tranche shall be deemed to have satisfied its VWAP Hurdle on "
        "the first date on which the foregoing thirty-day volume weighted "
        "average price condition has been met, even if such date occurs "
        "before the corresponding deployment milestone has been achieved. "
        "Vesting of such Tranche shall nonetheless be deferred until both "
        "conditions have been satisfied.",
    ]),

    (4, "DEPLOYMENT CERTIFICATION FOR FINAL TRANCHE", [
        "In addition to the requirements of Section 2 and Section 3, the "
        "vesting of the fourth Tranche is contingent on the delivery to "
        "the Company of a written certification by the Holder, signed by "
        "an executive officer of the Holder, confirming that the Holder "
        "has successfully deployed Seller’s GPU Units at scale in "
        "production-grade workloads and that the performance, reliability, "
        "and supportability of such deployment meet or exceed the "
        "specifications set forth in Exhibit A to the Purchase Agreement "
        "(the “Deployment-at-Scale Certification”).",

        "The Deployment-at-Scale Certification shall be delivered no "
        "earlier than the first date on which both the Tranche 4 Milestone "
        "and the fourth-Tranche VWAP Hurdle have been satisfied. The "
        "Company may, within thirty (30) days following receipt of the "
        "Deployment-at-Scale Certification, request reasonable supporting "
        "evidence of the matters certified therein, and the Holder shall "
        "respond to such request in good faith. Vesting of the fourth "
        "Tranche shall occur upon the Company’s receipt of such "
        "certification and any supporting evidence reasonably requested.",
    ]),

    (5, "ANTI-DILUTION ADJUSTMENTS", [
        "If, at any time after the Issue Date and prior to the expiration "
        "or full exercise of this Warrant, the Company effects a stock "
        "split, reverse stock split, stock dividend, recapitalization, "
        "reorganization, or similar event affecting the Company’s common "
        "stock generally, the number of Warrant Shares issuable upon "
        "exercise of this Warrant and the Exercise Price shall be "
        "proportionately adjusted such that the aggregate Exercise Price "
        "payable upon exercise of this Warrant, and the proportion of the "
        "outstanding common stock issuable in respect of this Warrant, "
        "shall remain substantially the same as immediately prior to such "
        "event.",

        "In the case of any consolidation, merger, sale of substantially "
        "all assets, or other reorganization in which the Company is not "
        "the surviving entity, this Warrant shall, immediately prior to the "
        "consummation of such transaction, become exercisable for the kind "
        "and amount of consideration that a holder of the number of "
        "Warrant Shares then issuable upon exercise of this Warrant would "
        "have been entitled to receive in such transaction, subject to "
        "the vesting conditions of Section 2, Section 3, and Section 4. "
        "The provisions of this Section 5 shall similarly apply to "
        "successive recapitalizations and reorganizations.",
    ]),

    (6, "TRANSFER RESTRICTIONS", [
        "This Warrant and any Warrant Shares issued upon exercise hereof "
        "may not be sold, assigned, pledged, hypothecated, or otherwise "
        "transferred by the Holder, in whole or in part, except (i) to "
        "an affiliate of the Holder that agrees in writing to be bound by "
        "the terms of this Warrant, or (ii) with the prior written consent "
        "of the Company, which consent shall not be unreasonably withheld, "
        "conditioned, or delayed.",

        "Any purported transfer of this Warrant or the Warrant Shares in "
        "violation of this Section 6 shall be null and void ab initio and "
        "shall not be recognized by the Company. The Company shall be "
        "entitled to refuse to register any such purported transfer on its "
        "books and records.",
    ]),

    (7, "EXERCISE PERIOD AND EXPIRATION", [
        "This Warrant may be exercised, in whole or in part, with respect "
        "to vested Warrant Shares at any time and from time to time during "
        "the period commencing on the Issue Date and ending at 5:00 p.m. "
        "Pacific Time on the date that is six (6) years after the Issue "
        "Date (the “Exercise Period”). Any portion of this Warrant that "
        "has not vested and been exercised on or before the expiration of "
        "the Exercise Period shall automatically terminate and be of no "
        "further force or effect.",

        "Exercise of vested Warrant Shares shall be effected by delivery "
        "to the Company of (i) a duly executed Notice of Exercise in the "
        "form attached hereto as Exhibit 1 and (ii) payment of the "
        "aggregate Exercise Price for the Warrant Shares being exercised, "
        "by wire transfer of immediately available funds or, at the "
        "Holder’s election, by net exercise pursuant to the procedures set "
        "forth in the Notice of Exercise.",
    ]),

    (8, "CONFIDENTIALITY", [
        "Each of the Company and the Holder agrees to maintain in "
        "confidence the existence and terms of this Warrant, except to the "
        "extent disclosure is required by applicable law, regulation, or "
        "the rules of any national securities exchange on which either "
        "Party’s securities are listed. The Parties acknowledge that the "
        "Company will be required to file a copy of this Warrant as an "
        "exhibit to a Current Report on Form 8-K and to describe the "
        "material terms hereof in such report.",

        "Nothing in this Section 8 shall restrict either Party’s ability "
        "to disclose this Warrant and its terms to its directors, "
        "officers, employees, accountants, attorneys, lenders, and other "
        "advisors who have a need to know such information and who are "
        "themselves bound by obligations of confidentiality.",
    ]),

    (9, "REPRESENTATIONS AND WARRANTIES OF THE COMPANY", [
        "The Company represents and warrants to the Holder that: (i) the "
        "Company is duly incorporated, validly existing, and in good "
        "standing under the laws of the State of Delaware; (ii) the "
        "execution, delivery, and performance of this Warrant have been "
        "duly authorized by all necessary corporate action on the part of "
        "the Company; (iii) this Warrant, when executed and delivered by "
        "the Company, will constitute the valid and binding obligation of "
        "the Company, enforceable against the Company in accordance with "
        "its terms; and (iv) the Warrant Shares, when issued upon "
        "exercise of this Warrant in accordance with its terms, will be "
        "duly authorized, validly issued, fully paid, and non-assessable, "
        "and free of preemptive rights and any liens or encumbrances "
        "imposed by or through the Company, other than restrictions on "
        "transfer set forth in Section 6 and under applicable securities "
        "laws.",

        "The Company further represents that it has reserved, and shall "
        "at all times during the Exercise Period keep reserved, out of "
        "its authorized but unissued shares of common stock, a sufficient "
        "number of shares to provide for the issuance of the maximum "
        "number of Warrant Shares issuable upon exercise of this Warrant, "
        "and that such reserved shares are and will remain free of any "
        "preemptive or similar rights of any other Person.",
    ]),

    (10, "REPRESENTATIONS OF THE HOLDER", [
        "The Holder represents and warrants to the Company that the "
        "Holder is acquiring this Warrant and the Warrant Shares for the "
        "Holder’s own account for investment purposes and not with a view "
        "to, or for sale in connection with, any distribution thereof "
        "within the meaning of the Securities Act of 1933, as amended "
        "(the “Securities Act”). The Holder acknowledges that this "
        "Warrant and the Warrant Shares have not been registered under "
        "the Securities Act or any applicable state securities laws, and "
        "that this Warrant and any Warrant Shares issued upon exercise "
        "hereof may not be offered or sold absent registration under, or "
        "an exemption from the registration requirements of, the "
        "Securities Act and any applicable state securities laws.",

        "The Holder is an “accredited investor” as defined in Rule 501(a) "
        "of Regulation D promulgated under the Securities Act and has "
        "such knowledge and experience in financial and business matters "
        "that it is capable of evaluating the merits and risks of its "
        "investment in the Warrant Shares and of protecting its own "
        "interests in connection with such investment.",
    ]),

    (11, "MISCELLANEOUS", [
        "Notices. All notices, requests, consents, and other "
        "communications required or permitted under this Warrant shall be "
        "in writing and shall be deemed duly given when delivered "
        "personally, three (3) business days after deposit with a "
        "nationally recognized overnight courier service with delivery "
        "receipt requested, or when sent by electronic mail with "
        "confirmation of receipt, in each case addressed to the recipient "
        "at the address set forth on the signature page or such other "
        "address as such Party may designate by written notice.",

        "Amendment; Waiver. This Warrant may be amended, modified, or "
        "supplemented only by a written instrument signed by the Company "
        "and the Holder. No waiver of any provision of this Warrant shall "
        "be effective unless set forth in a writing signed by the Party "
        "against whom such waiver is to be enforced, and no waiver of any "
        "breach of this Warrant shall be deemed a waiver of any "
        "subsequent breach.",

        "Severability. If any provision of this Warrant is held by a "
        "court of competent jurisdiction to be invalid, illegal, or "
        "unenforceable, such provision shall be deemed modified to the "
        "minimum extent necessary to make it valid, legal, and "
        "enforceable, and the remaining provisions of this Warrant shall "
        "continue in full force and effect.",

        "Governing Law. This Warrant shall be governed by and construed "
        "in accordance with the laws of the State of Delaware, without "
        "regard to its conflicts of law principles. The Parties consent "
        "to the exclusive jurisdiction of the state and federal courts "
        "located in Wilmington, Delaware with respect to any dispute "
        "arising out of or relating to this Warrant.",

        "Counterparts; Electronic Signatures. This Warrant may be "
        "executed in one or more counterparts, each of which shall be "
        "deemed an original and all of which together shall constitute a "
        "single instrument. Signatures delivered by electronic means, "
        "including portable document format and electronic signature "
        "services, shall be deemed original signatures for all purposes.",

        "Entire Agreement. This Warrant, together with the Purchase "
        "Agreement, constitutes the entire agreement between the Company "
        "and the Holder with respect to the subject matter hereof and "
        "supersedes all prior or contemporaneous oral or written "
        "agreements, communications, and understandings with respect "
        "thereto. In the event of any conflict between the provisions of "
        "this Warrant and the Purchase Agreement, the provisions of this "
        "Warrant shall control with respect to the subject matter hereof.",
    ]),
]

SIGNATURE_BLOCK = (
    "IN WITNESS WHEREOF, the Company has caused this Warrant to be issued "
    "as of the Issue Date.\n\n"
    "ADVANCED MICRO DEVICES, INC.\n"
    "By: ____________________________\n"
    "Name: __________________________\n"
    "Title: _________________________\n\n"
    "Acknowledged and agreed by Holder:\n"
    "META PLATFORMS, INC.\n"
    "By: ____________________________\n"
    "Name: __________________________\n"
    "Title: _________________________"
)
