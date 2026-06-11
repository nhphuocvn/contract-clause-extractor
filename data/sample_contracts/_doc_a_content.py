"""Canonical text of the synthetic GPU Cloud Product Purchase Agreement (Doc A).

Single source of truth — both DOCX and PDF renderers consume this so the two
formats cannot drift. Every commercial term required by KICKOFF.md Deliverable 0
is embedded in the prose below; the corresponding entries in
`ground_truth.json` reference these sections by number.

The document is fictional. The party names are used as illustrative stand-ins;
nothing here represents a real agreement between Advanced Micro Devices, Inc.
and Meta Platforms, Inc.
"""

TITLE = "GPU CLOUD PRODUCT PURCHASE AGREEMENT"

NOTICE = (
    "SYNTHETIC — FICTIONAL — FOR DEMO USE ONLY. This document is a generated "
    "sample used to test the Deal Economics Copilot. It is not an actual "
    "contract between any real parties and does not reflect the terms of any "
    "real transaction. Any resemblance to real commercial terms is "
    "coincidental and incidental to the demonstration purpose."
)

PREAMBLE = (
    "This GPU Cloud Product Purchase Agreement (this “Agreement”) is entered "
    "into and effective as of February 1, 2026 (the “Effective Date”), by and "
    "between Advanced Micro Devices, Inc., a Delaware corporation with its "
    "principal place of business at 2485 Augustine Drive, Santa Clara, "
    "California 95054 (“Seller”), and Meta Platforms, Inc., a Delaware "
    "corporation with its principal place of business at 1 Meta Way, "
    "Menlo Park, California 94025 (“Buyer”). Seller and Buyer are each a "
    "“Party” and collectively the “Parties.”"
)

RECITALS = (
    "WHEREAS, Seller designs and manufactures high-performance graphics "
    "processing units intended for artificial intelligence training and "
    "inference workloads, including its MI355X-class accelerator products; "
    "and WHEREAS, Buyer operates large-scale data center infrastructure and "
    "wishes to procure such products from Seller on a multi-year committed "
    "basis to support its planned generative artificial intelligence "
    "deployments; NOW, THEREFORE, in consideration of the mutual covenants "
    "set forth herein, and for other good and valuable consideration, the "
    "receipt and sufficiency of which are hereby acknowledged, the Parties "
    "agree as follows:"
)

# Each entry: (section_number, ALL_CAPS_TITLE, [paragraph1, paragraph2, ...])
SECTIONS: list[tuple[int, str, list[str]]] = [
    (1, "DEFINITIONS", [
        "Capitalized terms used in this Agreement shall have the meanings set "
        "forth below or as otherwise defined herein. References to a “Section” "
        "or “Exhibit” are references to a Section of, or Exhibit to, this "
        "Agreement unless otherwise expressly stated. The words “include,” "
        "“includes,” and “including” shall be deemed followed by the words "
        "“without limitation.” The headings of Sections are inserted for "
        "convenience only and shall not affect the construction of this "
        "Agreement.",

        "“Affiliate” means, with respect to any Person, any other Person "
        "that, directly or indirectly through one or more intermediaries, "
        "controls, is controlled by, or is under common control with such "
        "Person, where “control” means the possession, directly or "
        "indirectly, of the power to direct or cause the direction of the "
        "management and policies of a Person, whether through the ownership "
        "of voting securities, by contract, or otherwise.",

        "“Business Day” means any day other than a Saturday, Sunday, or day "
        "on which commercial banks in San Francisco, California are "
        "authorized or required by law to be closed.",

        "“GPU Unit” means one (1) Seller MI355X-class graphics processing unit "
        "accelerator, delivered in the form factor specified in Exhibit A and "
        "meeting the technical specifications attached thereto, together with "
        "the firmware, drivers, and reference software stack reasonably "
        "necessary to operate such accelerator for Buyer’s intended workloads.",

        "“Committed Units” means the cumulative number of GPU Units that Buyer "
        "has agreed to purchase under this Agreement, totaling one hundred "
        "fifty thousand (150,000) GPU Units over the Initial Term, as further "
        "detailed in Section 3.",

        "“Quarter” means a calendar quarter of three (3) consecutive months "
        "beginning on the first day of February, May, August, or November of "
        "each year during the Term. “Year” means the consecutive twelve-month "
        "period beginning on the Effective Date or any anniversary thereof.",

        "“Base ASP” means the per-unit base average selling price set forth "
        "in Section 4. “Net ASP” means the Base ASP after application of the "
        "rebates set forth in Section 5 and any other adjustments expressly "
        "contemplated by this Agreement.",

        "“Order” means a binding written purchase order issued by Buyer to "
        "Seller pursuant to this Agreement and the Quarterly Delivery "
        "Schedule. “Quarterly Delivery Schedule” has the meaning given in "
        "Section 3.",

        "“Person” means any individual, corporation, limited liability "
        "company, partnership, trust, unincorporated organization, "
        "governmental authority, or other entity.",

        "“Specifications” means the technical, performance, reliability, and "
        "compliance specifications applicable to GPU Units, as set forth in "
        "Exhibit A and as may be updated from time to time by Seller, "
        "provided that no such update shall materially diminish the "
        "performance characteristics of the GPU Units delivered under this "
        "Agreement.",
    ]),

    (2, "TERM", [
        "The initial term of this Agreement shall commence on the Effective "
        "Date and continue for a period of three (3) years thereafter (the "
        "“Initial Term”), unless earlier terminated in accordance with "
        "Section 11. This Agreement shall not automatically renew, and any "
        "extension of the Initial Term shall require a written amendment "
        "executed by both Parties.",
    ]),

    (3, "COMMITTED VOLUME AND DELIVERY SCHEDULE", [
        "During the Initial Term, Buyer shall purchase, and Seller shall sell "
        "and deliver, an aggregate of one hundred fifty thousand (150,000) "
        "GPU Units (the “Committed Units”) in accordance with the quarterly "
        "ramp set forth in this Section 3. The Parties acknowledge that the "
        "ramp reflects a gradual build-out in Year 1, a peak deployment in "
        "Year 2, and a managed taper in Year 3 as Buyer transitions to "
        "successor product generations.",

        "The Committed Units shall be delivered in the following per-Quarter "
        "quantities (the “Quarterly Delivery Schedule”): in Year 1, seven "
        "thousand (7,000) GPU Units in the first Quarter, nine thousand "
        "(9,000) in the second Quarter, twelve thousand (12,000) in the "
        "third Quarter, and fifteen thousand (15,000) in the fourth Quarter, "
        "for a Year 1 total of forty-three thousand (43,000) GPU Units; in "
        "Year 2, eighteen thousand (18,000) in the first Quarter, twenty "
        "thousand (20,000) in the second Quarter, eighteen thousand (18,000) "
        "in the third Quarter, and sixteen thousand (16,000) in the fourth "
        "Quarter, for a Year 2 total of seventy-two thousand (72,000) GPU "
        "Units; and in Year 3, thirteen thousand (13,000) in the first "
        "Quarter, eleven thousand (11,000) in the second Quarter, seven "
        "thousand (7,000) in the third Quarter, and four thousand (4,000) in "
        "the fourth Quarter, for a Year 3 total of thirty-five thousand "
        "(35,000) GPU Units.",

        "Buyer shall issue Orders no later than sixty (60) days prior to the "
        "beginning of each Quarter, specifying the desired delivery dates "
        "within such Quarter. Seller shall confirm each Order in writing "
        "within ten (10) Business Days of receipt. Buyer may, with at least "
        "forty-five (45) days’ prior written notice, request that up to "
        "fifteen percent (15%) of the quantity scheduled for any Quarter be "
        "shifted to the immediately following Quarter, subject to Seller’s "
        "good-faith capacity availability, provided that the aggregate "
        "Committed Units for the Initial Term shall not be reduced.",
    ]),

    (4, "PRICING", [
        "The base average selling price for each GPU Unit shall be twenty-"
        "five thousand United States dollars (US$25,000) per GPU Unit (the "
        "“Base ASP”), exclusive of taxes, duties, freight, and insurance, "
        "which shall be borne by Buyer in accordance with Section 8.",

        "The Base ASP shall be firm for the Initial Term and shall not be "
        "subject to upward adjustment except as expressly set forth in this "
        "Agreement or by written amendment signed by both Parties. The Base "
        "ASP is subject to the downward adjustments set forth in Section 5 "
        "(volume rebates) and Section 9 (most-favored-nation price "
        "protection).",
    ]),

    (5, "VOLUME REBATES", [
        "Seller shall provide Buyer with tiered volume rebates against the "
        "Base ASP based on Buyer’s cumulative purchases of GPU Units under "
        "this Agreement, measured from the Effective Date. The rebate rates "
        "are as follows: (i) for cumulative purchases above thirty thousand "
        "(30,000) GPU Units, three percent (3%) of the Base ASP; (ii) for "
        "cumulative purchases above seventy-five thousand (75,000) GPU "
        "Units, five percent (5%) of the Base ASP; and (iii) for cumulative "
        "purchases above one hundred twenty thousand (120,000) GPU Units, "
        "seven percent (7%) of the Base ASP.",

        # Deliberately ambiguous clause — see ground_truth.json
        # ambiguity_note. The text is silent on whether crossing a tier
        # mid-Year applies to volume purchased earlier in the Year or only
        # to volume purchased thereafter.
        "Rebates earned pursuant to this Section 5 shall be settled annually "
        "in arrears, within forty-five (45) days following the end of each "
        "Year. The applicable rebate tier shall be determined by reference "
        "to Buyer’s cumulative GPU Unit purchases as of the end of the "
        "relevant Year. Where Buyer’s cumulative purchases cross a tier "
        "threshold during a Year, the higher tier shall apply, and Seller "
        "shall calculate the rebate payable in good faith based on volumes "
        "purchased during such Year.",

        "Rebates shall be paid by Seller to Buyer by wire transfer of "
        "immediately available funds, or, at Buyer’s election, applied as a "
        "credit against undisputed invoices then outstanding or next "
        "becoming due.",
    ]),

    (6, "TAKE-OR-PAY OBLIGATION", [
        "For each Year of the Initial Term, Buyer shall purchase, or in "
        "lieu thereof pay for, a number of GPU Units not less than eighty "
        "percent (80%) of the aggregate Quarterly Delivery Schedule for "
        "such Year (the “Annual Minimum”). To the extent Buyer’s actual "
        "purchases in any Year fall below the Annual Minimum for that Year, "
        "Buyer shall pay Seller, within sixty (60) days after the end of "
        "such Year, an amount equal to the Base ASP multiplied by the "
        "shortfall in GPU Units (the “Take-or-Pay Payment”).",

        "GPU Units paid for but not taken in a given Year shall be "
        "considered “Banked Units” and may be drawn down by Buyer in any "
        "subsequent Quarter during the Initial Term without further "
        "payment, subject to Seller’s reasonable capacity availability. "
        "Banked Units that remain undrawn at the expiration of the Initial "
        "Term shall be forfeited without refund.",
    ]),

    (7, "PREPAYMENT", [
        "On the Effective Date, Buyer shall pay Seller a non-refundable "
        "prepayment of five hundred million United States dollars "
        "(US$500,000,000) (the “Prepayment”) by wire transfer of immediately "
        "available funds. The Prepayment shall be held by Seller and applied "
        "against amounts invoiced to Buyer for GPU Units delivered under "
        "this Agreement, beginning with the first Order delivered after the "
        "Effective Date.",

        "Seller shall apply a portion of the Prepayment against each "
        "invoice issued under this Agreement until the Prepayment is "
        "exhausted, with such portion equal to twenty percent (20%) of "
        "the invoiced amount or such other percentage as the Parties may "
        "agree in writing. Seller’s monthly statements shall reflect the "
        "remaining Prepayment balance.",
    ]),

    (8, "PAYMENT TERMS", [
        "Seller shall invoice Buyer upon shipment of GPU Units against each "
        "Order. Invoiced amounts shall be due and payable by Buyer within "
        "ninety (90) days after the date of the invoice (net 90), without "
        "offset or deduction except as expressly permitted under this "
        "Agreement. Buyer shall pay all undisputed invoices by wire transfer "
        "of immediately available funds to the account designated by Seller "
        "in writing.",

        "Amounts properly disputed in good faith by Buyer shall be set forth "
        "in a written notice to Seller within thirty (30) days of the "
        "invoice date, and the undisputed portion shall be paid in "
        "accordance with this Section 8. Disputed amounts shall be "
        "addressed in accordance with the dispute resolution procedures of "
        "Section 15. Buyer shall be responsible for all applicable sales, "
        "use, value-added, and similar transactional taxes, and for "
        "freight, insurance, and customs duties associated with delivery of "
        "GPU Units.",
    ]),

    (9, "PRICE PROTECTION", [
        "If, during the Initial Term, Seller enters into an agreement with "
        "any third-party customer for the sale of GPU Units of substantially "
        "comparable specifications at a per-unit base price that is lower "
        "than the Base ASP, in volumes substantially comparable to or "
        "smaller than the Committed Units, then the Base ASP applicable to "
        "GPU Units delivered to Buyer in the Quarter immediately following "
        "Seller’s execution of such third-party agreement, and thereafter "
        "for the remainder of the Initial Term, shall be reduced to match "
        "the lower per-unit base price (the “MFN Price”).",

        "Adjustments under this Section 9 shall apply on a prospective basis "
        "only, and shall not entitle Buyer to refunds, credits, or "
        "retroactive adjustments with respect to GPU Units delivered prior "
        "to the effective date of the adjustment. Seller shall notify "
        "Buyer in writing within thirty (30) days following execution of "
        "any such third-party agreement that triggers this Section 9, and "
        "shall provide reasonable evidence of the lower per-unit base "
        "price, subject to redaction of competitively sensitive third-party "
        "information.",
    ]),

    (10, "DELIVERY AND SUPPLY COMMITMENT", [
        "Seller commits to allocate sufficient manufacturing capacity, in "
        "good faith and on a Quarter-by-Quarter basis, to meet the "
        "Quarterly Delivery Schedule. Seller shall use commercially "
        "reasonable efforts to deliver each Order on or before the "
        "delivery date confirmed pursuant to Section 3, with title and "
        "risk of loss transferring to Buyer at the delivery destination "
        "set forth in the applicable Order.",

        "In the event Seller fails to deliver, in any given Quarter, the "
        "GPU Unit quantity confirmed in respect of such Quarter, Seller "
        "shall pay to Buyer liquidated damages equal to two percent (2%) "
        "of the aggregate Order value for such Quarter for each full week "
        "of delay, calculated from the originally confirmed delivery date. "
        "Liquidated damages payable under this Section 10 for any "
        "individual Quarter shall not exceed, in aggregate, ten percent "
        "(10%) of the Order value for such Quarter. The Parties agree that "
        "such liquidated damages represent a reasonable estimate of the "
        "harm that Buyer would suffer as a result of late delivery and "
        "are not a penalty.",
    ]),

    (11, "TERMINATION", [
        "Either Party may terminate this Agreement for cause upon written "
        "notice to the other Party if the other Party materially breaches "
        "this Agreement and fails to cure such breach within thirty (30) "
        "days after receipt of written notice describing such breach in "
        "reasonable detail. Seller may terminate this Agreement for cause, "
        "or suspend deliveries, if Buyer fails to pay any undisputed "
        "amount within ninety (90) days following the applicable due date.",

        "Buyer may terminate this Agreement for convenience, in whole but "
        "not in part, upon one hundred eighty (180) days’ prior written "
        "notice to Seller. In the event of termination for convenience by "
        "Buyer under this Section 11, Buyer shall pay Seller, on or before "
        "the effective date of termination, a wind-down fee equal to "
        "twenty-five percent (25%) of the aggregate Base ASP of the "
        "Committed Units that remain undelivered as of the effective date "
        "of termination (the “Wind-Down Fee”). The Wind-Down Fee shall be "
        "Seller’s sole and exclusive monetary remedy for Buyer’s "
        "termination for convenience, and shall be paid net of any "
        "unapplied portion of the Prepayment then held by Seller.",
    ]),

    (12, "LIMITATION OF LIABILITY", [
        "EXCEPT FOR (A) BREACHES OF CONFIDENTIALITY OBLIGATIONS UNDER "
        "SECTION 14, (B) A PARTY’S INDEMNIFICATION OBLIGATIONS WITH RESPECT "
        "TO THIRD-PARTY CLAIMS OF INTELLECTUAL PROPERTY INFRINGEMENT, AND "
        "(C) AMOUNTS OWED TO SELLER FOR DELIVERED GPU UNITS OR PURSUANT TO "
        "SECTION 6 OR SECTION 7, EACH PARTY’S AGGREGATE LIABILITY UNDER OR "
        "RELATING TO THIS AGREEMENT SHALL NOT EXCEED THE TOTAL AMOUNTS "
        "PAID OR PAYABLE BY BUYER TO SELLER UNDER THIS AGREEMENT DURING "
        "THE TWELVE (12) MONTHS IMMEDIATELY PRECEDING THE EVENT GIVING "
        "RISE TO THE LIABILITY.",

        "Indemnification obligations of either Party with respect to "
        "third-party claims alleging that the GPU Units (in the case of "
        "Seller’s indemnification) or Buyer’s use thereof in breach of "
        "this Agreement (in the case of Buyer’s indemnification) infringe "
        "any patent, copyright, trademark, or trade secret of a third "
        "party shall not be subject to the cap set forth in the preceding "
        "paragraph. NEITHER PARTY SHALL BE LIABLE TO THE OTHER FOR ANY "
        "INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE "
        "DAMAGES, OR FOR LOST PROFITS OR LOST REVENUE, ARISING UNDER OR "
        "RELATING TO THIS AGREEMENT, EVEN IF ADVISED OF THE POSSIBILITY "
        "OF SUCH DAMAGES.",
    ]),

    (13, "WARRANT ISSUANCE", [
        "Concurrently with the execution of this Agreement, Seller shall "
        "issue to Buyer a warrant to purchase shares of Seller’s common "
        "stock pursuant to the Warrant Agreement of even date herewith "
        "by and between Seller and Buyer (the “Warrant Agreement”). The "
        "number of shares, exercise price, vesting conditions, and other "
        "terms of such warrant are set forth in the Warrant Agreement, "
        "which is incorporated herein by reference for purposes of "
        "construing the Parties’ overall commercial arrangement.",

        "The Parties acknowledge that the warrant constitutes "
        "consideration payable by Seller to Buyer in connection with this "
        "Agreement, and the financial and accounting effects of such "
        "warrant shall be evaluated by each Party in accordance with "
        "applicable accounting standards. Neither this Section 13 nor the "
        "Warrant Agreement shall be construed to modify any of the "
        "commercial terms set forth elsewhere in this Agreement.",
    ]),

    (14, "CONFIDENTIALITY", [
        "Each Party (the “Receiving Party”) agrees to maintain in "
        "confidence all non-public information disclosed to it by the "
        "other Party (the “Disclosing Party”) in connection with this "
        "Agreement, including pricing, volumes, technical specifications, "
        "and business plans (collectively, “Confidential Information”), "
        "and to use such Confidential Information solely for purposes of "
        "performing its obligations and exercising its rights under this "
        "Agreement.",

        "The obligations of confidentiality set forth in this Section 14 "
        "shall survive for a period of five (5) years following the "
        "expiration or earlier termination of this Agreement, except with "
        "respect to trade secrets, which shall be maintained in "
        "confidence for so long as such information retains its character "
        "as a trade secret under applicable law. Confidential Information "
        "shall not include information that (i) is or becomes publicly "
        "available without breach of this Agreement, (ii) is independently "
        "developed by the Receiving Party without reference to the "
        "Disclosing Party’s Confidential Information, or (iii) is "
        "rightfully received by the Receiving Party from a third party "
        "without restriction.",
    ]),

    (15, "REPRESENTATIONS AND WARRANTIES", [
        "Each Party represents and warrants to the other Party that: (i) it "
        "is duly organized, validly existing, and in good standing under the "
        "laws of its jurisdiction of organization; (ii) it has all requisite "
        "corporate power and authority to enter into this Agreement and to "
        "perform its obligations hereunder; (iii) the execution, delivery, "
        "and performance of this Agreement have been duly authorized by all "
        "necessary corporate action on its part; and (iv) this Agreement, "
        "when executed and delivered, will constitute the legal, valid, and "
        "binding obligation of such Party, enforceable against such Party in "
        "accordance with its terms, subject to applicable bankruptcy, "
        "insolvency, reorganization, moratorium, and similar laws affecting "
        "creditors’ rights generally.",

        "Seller further represents and warrants that GPU Units delivered "
        "hereunder will, for a period of twelve (12) months following "
        "delivery, conform in all material respects to the Specifications "
        "and will be free from material defects in materials and "
        "workmanship under normal use. Seller’s sole and exclusive "
        "obligation, and Buyer’s sole and exclusive remedy, for any breach "
        "of the foregoing warranty shall be, at Seller’s option, repair, "
        "replacement, or refund of the purchase price of the affected GPU "
        "Unit. EXCEPT AS EXPRESSLY SET FORTH IN THIS SECTION 15, GPU UNITS "
        "ARE PROVIDED “AS IS” AND SELLER MAKES NO OTHER WARRANTIES, "
        "EXPRESS OR IMPLIED, INCLUDING ANY IMPLIED WARRANTIES OF "
        "MERCHANTABILITY OR FITNESS FOR A PARTICULAR PURPOSE.",

        "Buyer represents and warrants that it will use the GPU Units in "
        "compliance with all applicable laws and regulations, including "
        "export-control and sanctions laws, and that it will not, directly "
        "or indirectly, export, re-export, or transfer GPU Units to any "
        "Person or destination prohibited by such laws.",
    ]),

    (16, "FORCE MAJEURE", [
        "Neither Party shall be liable for any failure or delay in the "
        "performance of its obligations under this Agreement (other than "
        "obligations to make payments of amounts then due) to the extent "
        "such failure or delay is caused by events beyond such Party’s "
        "reasonable control, including acts of God, war, terrorism, civil "
        "unrest, epidemic, pandemic, governmental orders, embargoes, "
        "earthquake, fire, flood, labor disputes, or interruptions in the "
        "supply of critical components or utilities (a “Force Majeure "
        "Event”), provided that the affected Party promptly notifies the "
        "other Party of the Force Majeure Event and uses commercially "
        "reasonable efforts to mitigate its effects.",

        "If a Force Majeure Event continues for more than ninety (90) "
        "consecutive days, the Party not affected by such event may "
        "terminate the unperformed portion of this Agreement, in whole or "
        "in part, upon written notice to the affected Party, without "
        "liability except for amounts then due and payable. The Quarterly "
        "Delivery Schedule and the Annual Minimums shall be equitably "
        "adjusted to reflect the duration and impact of any Force Majeure "
        "Event affecting Seller’s ability to deliver.",
    ]),

    (17, "GOVERNING LAW AND DISPUTE RESOLUTION", [
        "This Agreement shall be governed by and construed in accordance "
        "with the laws of the State of Delaware, without regard to its "
        "conflicts of law principles. Any dispute arising under or "
        "relating to this Agreement shall first be referred to senior "
        "executives of each Party for good-faith resolution. If such "
        "executives are unable to resolve the dispute within thirty (30) "
        "days of referral, the dispute shall be finally resolved by "
        "binding arbitration administered by the American Arbitration "
        "Association under its Commercial Arbitration Rules, with the seat "
        "of arbitration in Wilmington, Delaware.",

        "Notwithstanding the foregoing, either Party may seek temporary or "
        "preliminary injunctive relief in any court of competent "
        "jurisdiction to prevent or restrain any actual or threatened "
        "breach of confidentiality or misappropriation of intellectual "
        "property. The prevailing Party in any arbitration or court "
        "proceeding shall be entitled to recover its reasonable attorneys’ "
        "fees and costs.",
    ]),

    (18, "INSURANCE", [
        "Each Party shall maintain, throughout the Initial Term and for a "
        "period of two (2) years following its expiration or earlier "
        "termination, insurance coverage in amounts customary for "
        "transactions of the size and nature contemplated by this "
        "Agreement, including: (i) commercial general liability insurance "
        "with limits of not less than five million United States dollars "
        "($5,000,000) per occurrence and ten million United States dollars "
        "($10,000,000) in the aggregate; (ii) products liability "
        "insurance with limits of not less than twenty-five million "
        "United States dollars ($25,000,000) per occurrence and fifty "
        "million United States dollars ($50,000,000) in the aggregate; "
        "(iii) workers’ compensation insurance in accordance with "
        "applicable statutory requirements; and (iv) cybersecurity and "
        "data breach insurance with limits of not less than twenty "
        "million United States dollars ($20,000,000) per occurrence.",

        "Each Party shall, upon written request, provide to the other "
        "Party certificates of insurance evidencing the foregoing "
        "coverage. The maintenance of such insurance shall not limit or "
        "otherwise affect either Party’s obligations or liabilities under "
        "this Agreement. The insurance maintained by either Party shall "
        "be primary with respect to its own acts and omissions and shall "
        "include a waiver of subrogation in favor of the other Party.",
    ]),

    (19, "COMPLIANCE WITH LAWS AND EXPORT CONTROLS", [
        "Each Party shall comply with all applicable laws, regulations, "
        "and orders of any governmental authority having jurisdiction "
        "over its activities under this Agreement, including those "
        "relating to bribery, anti-corruption, export controls, "
        "sanctions, money laundering, data protection, and the "
        "environment. Without limiting the foregoing, each Party "
        "represents that it has implemented, and shall maintain "
        "throughout the Initial Term, a written compliance program "
        "reasonably designed to prevent violations of the U.S. Foreign "
        "Corrupt Practices Act of 1977, the U.K. Bribery Act 2010, and "
        "comparable anti-corruption laws of other jurisdictions.",

        "Buyer acknowledges that GPU Units may be subject to the U.S. "
        "Export Administration Regulations and similar laws of other "
        "jurisdictions, including controls applicable to advanced "
        "computing items. Buyer shall not, directly or indirectly, "
        "export, re-export, or transfer any GPU Unit to (i) any "
        "destination subject to a comprehensive U.S. embargo, (ii) any "
        "Person designated on the U.S. Department of the Treasury’s "
        "Specially Designated Nationals and Blocked Persons List or the "
        "U.S. Department of Commerce’s Entity List, or (iii) any end use "
        "prohibited under applicable export-control laws, without first "
        "obtaining any required governmental authorizations.",
    ]),

    (20, "AUDIT", [
        "Each Party shall maintain complete and accurate books and "
        "records related to its performance under this Agreement, "
        "including with respect to deliveries, invoicing, rebate "
        "calculations, and the application of the Prepayment, for a "
        "period of not less than five (5) years following the "
        "expiration or earlier termination of this Agreement. Each "
        "Party shall have the right, upon thirty (30) days’ prior "
        "written notice and not more than once per calendar year, to "
        "engage an independent, nationally recognized accounting firm "
        "subject to customary confidentiality obligations to audit such "
        "books and records of the other Party solely for purposes of "
        "verifying compliance with the financial provisions of this "
        "Agreement.",

        "If an audit conducted pursuant to this Section 20 reveals an "
        "underpayment or overpayment of any amount payable under this "
        "Agreement, the responsible Party shall promptly pay the "
        "deficiency or refund the overpayment, as applicable, together "
        "with interest at the rate of five percent (5%) per annum from "
        "the date the amount was originally due. If the audit reveals "
        "an underpayment or overpayment in excess of five percent (5%) "
        "of the amount properly due, the audited Party shall also bear "
        "the reasonable costs of the audit.",
    ]),

    (21, "MISCELLANEOUS", [
        "Notices. All notices, requests, consents, and other communications "
        "required or permitted under this Agreement shall be in writing and "
        "shall be deemed duly given when delivered personally, three (3) "
        "Business Days after deposit with a nationally recognized overnight "
        "courier service with delivery receipt requested, or, in the case "
        "of notices among the Parties’ in-house legal teams, when sent by "
        "electronic mail with confirmation of receipt, in each case "
        "addressed to the recipient at the address set forth on the "
        "signature page or such other address as such Party may designate "
        "by written notice.",

        "Assignment. Neither Party may assign or delegate its rights or "
        "obligations under this Agreement, in whole or in part, without "
        "the prior written consent of the other Party, except that either "
        "Party may assign this Agreement, without consent, to an Affiliate "
        "of such Party or to a successor in connection with a merger, "
        "consolidation, or sale of all or substantially all of such "
        "Party’s assets or business to which this Agreement relates, "
        "provided that the assignee assumes in writing the assigning "
        "Party’s obligations hereunder. Any purported assignment in "
        "violation of this Section shall be null and void.",

        "Entire Agreement; Amendment. This Agreement, together with the "
        "Warrant Agreement and the Exhibits attached hereto, constitutes "
        "the entire agreement between the Parties with respect to the "
        "subject matter hereof and supersedes all prior or contemporaneous "
        "oral or written agreements, communications, and understandings "
        "with respect thereto. No amendment, modification, or waiver of "
        "any provision of this Agreement shall be effective unless set "
        "forth in a writing signed by an authorized representative of "
        "each Party.",

        "Severability. If any provision of this Agreement is held by a "
        "court or arbitral tribunal of competent jurisdiction to be "
        "invalid, illegal, or unenforceable, such provision shall be "
        "deemed modified to the minimum extent necessary to make it "
        "valid, legal, and enforceable, and the remaining provisions of "
        "this Agreement shall continue in full force and effect.",

        "No Waiver. The failure or delay of either Party to exercise any "
        "right or remedy under this Agreement shall not constitute a "
        "waiver of such right or remedy, and no single or partial "
        "exercise of any right or remedy shall preclude any further "
        "exercise thereof. All rights and remedies under this Agreement "
        "are cumulative and not exclusive of any rights or remedies "
        "provided by law.",

        "Counterparts; Electronic Signatures. This Agreement may be "
        "executed in one or more counterparts, each of which shall be "
        "deemed an original and all of which together shall constitute a "
        "single instrument. Signatures delivered by electronic means, "
        "including portable document format and electronic signature "
        "services, shall be deemed original signatures for all purposes.",

        "Independent Contractors. The Parties are independent contractors, "
        "and nothing in this Agreement shall be construed to create a "
        "partnership, joint venture, agency, or employment relationship "
        "between them. Neither Party shall have the authority to bind the "
        "other Party or to incur any obligation on its behalf, except as "
        "expressly authorized in writing.",
    ]),
]

SIGNATURE_BLOCK = (
    "IN WITNESS WHEREOF, the Parties have caused this Agreement to be "
    "executed by their duly authorized representatives as of the Effective "
    "Date.\n\n"
    "ADVANCED MICRO DEVICES, INC.\n"
    "By: ____________________________\n"
    "Name: __________________________\n"
    "Title: _________________________\n\n"
    "META PLATFORMS, INC.\n"
    "By: ____________________________\n"
    "Name: __________________________\n"
    "Title: _________________________"
)
