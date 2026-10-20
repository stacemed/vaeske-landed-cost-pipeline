"""Tests for components_register.py, grounded in real WHSM (Shenzhen
Minzhi BYJ Trading Company) and SBIC (Shanghai Beone Industrial Co.)
documents downloaded and inspected directly (2026-10-20) -- see the
module's own docstring for the real-world messiness each fixture
confirms.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from landed_cost.models.documents import SourceDocument
from landed_cost.sheets.components_register import (
    ComponentRegisterRow,
    balance_installment_number,
    build_components_register_rows,
    extract_payment_amount,
    extract_total_order_amount,
)


WHSM_DEPOSIT_INVOICE_TEXT = 'INV-24Q4SLV24Q4 SLEEVESShenzhen Minzhi BYJ Trading CompanyRoom 2801,Building 3A, Shijichuncheng 4th Phrase, Longhua District,Shenzhen,ChinaINVOICE\n30% Down Payment Due:$3,999.60Subject:Q4-2K X12QT Sleeve & 2K X26QT Sleeve #                Item & DescriptionQty(PCS)Rate (Current)Sub Category Amount112 QT Sleeve2000$2.828$5,656.000226QT Sleeve2000$3.838$7,676.000NoteIncluding local freight to warehouse inland ChinaSub Total $13,332.00Deposit  30%$3,999.60Balance dued before dispatch$9,332.40______________________________________________________________________________________________________Thanks for your business.______________________________________________________________________________________________________SAY 30% Down Payment U.S DOLLARS  THREE THOUSAND  AND NINE  HUNDRED  AND NINTY NINE POINT SIXTY  ONLYBELOW 👇 Payment Option -Via Fedwire or WireDomestic Payment in USA(Fedwire or wire-(Same day arrival in destination account)Please make a domestic payment via Fedwire to the account details below:*Account Number: 8333783388*ABA/ Routing Number: 026073008*Account Name: Shenzhen Minzhi BYJ Trading Company*Bank Name: Community Federal Savings Bank*Bank Address: Seventh Avenue, New York, NY 10019, USType of Account: Business AccountRemark-Please include the following memo/Message to receiver when making a payment:[ Black Oak Essentials LLC] [INV-JUN24USQ4CRP] [Q4 COPONENTS]SignatureWHYMON HUANG'


WHSM_BALANCE_INVOICE_TEXT = 'Shenzhen Minzhi BYJ Trading Company \nRoom 2801,Building 3A, \nShijichuncheng 4th Phrase, \nLonghua District,Shenzhen,China \nINVOICE\nOrder Codes. Description  & Specification Quantity Unit price ( USD) Amount （USD ）\nJD-P1220 12QT Container,36.5*26.5*20CM 2,000 PCS $4.00 $8000.00\nJD-P1201 12QT Lid,with notch,53*32.5CM 2,000 PCS $1.96 $3920.00\nTotal Invoice Amount $11,920.00 )\nTotal Invoice Cost ： $11,920.00 )\n30% Deposit Via Wise: $3,576.00 )\n70% Balance: $8,344.00 )\nSAY DEPOSIT U.S DOLLARS TOTALLY  THREE THOUSAND FIVE HUNDRED SEVENTY SIX ONLY\nNotes\n__Thanks for your business.____________________________________________________________________________________________________\nRemark:BELOW ARE OPTIONAL BANK INFORMATIONS\nBELOW 👇 Payment Option -Via Fedwire or Wire\nDomestic Payment in USA(Fedwire or wire-(Same day arrival in destination account)\nPlease make a domestic payment via Fedwire to the account details below:\n*Account Number: 8333783388\n*ABA/ Routing Number: 026073008\n*Account Name: Shenzhen Minzhi BYJ Trading Company\n*Bank Name: Community Federal Savings Bank\n*Bank Address: Seventh Avenue, New York, NY 10019, US\nType of Account: Business Account\nRemark-Please include the following memo/Message to receiver when making a payment:\n[ Black Oak Essentials LLC] [USCTN12QT-2403-01] [12QT Containers&Lids]\nSignature\nWHYMON \nHUANG'


WHSM_FULL_INVOICE_TEXT = 'INV-25Q1SLV&26QTINNERBOX\nWhymon Huang \nINVOICE\nBalance Payment Due:\n$343.20\nSubject:\nLids cutting BOM & Cutting cost\n#                Item & Description Qty(PCS) Rate (Current) Sub Category Amount\n1BOM Moulding 2 $138.000 $276.000\n226QT Lids 36 $0.800 $28.800\n212QT Lids 48 $0.800 $38.400\nNote Including local freight to warehouse inland China\nSub Total $343.20\n______________________________________________________________________________________________________\nThanks for your business.\n______________________________________________________________________________________________________\nPayment Option-Wise\nAccount Name: WEIMIN HUANG\nAccount:122794967@qq.com\nBundle Phone Number-0086 13428722890\nSignature\nWHYMON HUANG'


WHSM_DEPOSIT_PCONF_TEXT = "Print or saveTOWHYMON FEDWIREUnited StatesFROMOPEX ...5268Available balancAMOUNT$3,999.60WIRE TRANSFERFEE$25.00TOTAL FROMACCOUNT$4,024.60SEND ON10/15/2024DELIVER BY10/15/2024MESSAGE TORECIPIENT'S BANKINV 24Q4SLVSTATUSSCHEDULEDCONFIRMATIONNUMBEROW00005011987833Send another wireCon\x00rmation\nYou submitted your wire on 10/12/2024 at 04:14 am Paci\x00c Time.10/12/24, 1:14 PMWire Money - Conﬁrmation | Wells Fargo\nhttps://connect.secure.wellsfargo.com/transferandpay/globalpay/transfers/home?st=1728731578&WFAppId=&SAMLart=AAQCQ%2BoEQCR14WDgSxaU4QNGC…1/1"


WHSM_BALANCE_INVOICE_JUMBLED_2025_TEXT = 'Shenzhen Minzhi BYJ Trading CompanyRoom 2801,Building 3A,Shijichuncheng 4th Phrase,Longhua District,Shenzhen,ChinaINVOICE\nTo: Black Oak Essentials LLCAttn: John Grattan1265 McConnell AveSanta Rosa, CA 95404United States of America#INV-25Q4RPC26S-B01Invoice Date: Jul 10, 2025Order Reference: US25Q4RPC26S\nDeposit  30%Down Payment 1 OF CONTAINER & LID:\nRemarks: Above Container Lids Price INcluding the CNC Cutting, all other prices IN-cluding local freights to get sent to destination warehouse in China$19,014.80\n$27,028.86$8,108.66\nBELOW \n Payment Option -Via Fedwire \nSignatureSubject:TERMEx-Work including local delivery112 QT Container 36.5*26.5*20CM1000$4.105$4,105.000212QT Lid 32.5*26.5CM1055$1.985$2,094.175326QT Container 53*32.5*20CM2000$6.845$13,690.000426QT Lid 53*32.5CM2103$3.395$7,139.685Sub Total \nThanks for your business.25 Q4 Repeat- X12QTSet K X26QT Set 1K& 2 BALANCE PAYMENT\n[INV--25Q4RPC26S-B1] [25Q4 Repeat COPONENTS]#                Item & DescriptionQty(PCS)Rate (Current)Sub Category Amount\nTTL Down Payment Amount $18,920.20Down Payment Considering Exchange Rate Change: 0.5%TTL Balance Payment Amount  $94.60$19,014.80____________________________________________________________________________________________________________________________________________________________________________________________________________SAY Balance Payment 1（for containers and lids)U.S DOLLARS   NINETEEN THOUSAND   AND  FOURTEEN POINT EIGHTY ONLYDomestic Payment in USA(Fedwire or wire-(Same day arrival in destination account)Please make a domestic payment via Fedwire to the account details below:*Account Number: 8333783388*ABA/ Routing Number: 026073008*Account Name: Shenzhen Minzhi BYJ Trading Company*Bank Name: Community Federal Savings Bank*Bank Address: Seventh Avenue, New York, NY 10019, USType of Account: Business AccountRemark-Please include the following memo/Message to receiver when making a payment:[ Black Oak Essentials LLC] WHYMON HUANG\n'


SBIC_ORDER_PAGE_TEXT = "3/7/24, 10:23 PM Trade Assurance Order Details\nhttps://biz.alibaba.com/ta/detail.htm?spm=a2700.12336162.0.0.5c6665aaCEKIpF&orderId=204243854001026990 1/3\nFreight Forwarding By Alibaba.com Fulﬁllment Services\nWe provide one-stop freight forwarding through \n , oﬀering competitive prices, 30-day locked-in quotes, and 24/7 online support.\xa0 \xa0 Learn more\nProduction Monitoring & Inspection Services\nTo help reduce risks in production delay and product conformityas low as  \xa0USD 48.00\n* Please make sure to select and pay for the service at least 7 working days before the shipment date .Home My Alibaba Order Management Order details \ue619 \ue619 \ue619\nTrade Assurance Order Shanghai Beone Industrial Co., Ltd. Order number: \xa0204243854001026990\nOrder Payment Dispatch Delivery Review\nInitial payment being processed\n· Mar. 7, 2024, 20:22:36 PST., you have submitted your credit/debit card payment. Your payment amount USD 1255.50 is currently being processed.\nThe payment is currently being processed. The payment result and order status will update within 30 minutes. If the payment is successful, the funds will reach the supplier's account within 1\nbusiness day. If the payment fails, Alibaba.com will notify you by email.\n\xa0\xa0 \xa0\xa0Payment\nView bank account list\nGet an initial quote\nAdd Service\nShipping details\n\ue625\nShipping time: \xa0Shipment not dispatched \xa0 Shipping method: \xa0Express\nPayment history \xa0\xa0\xa0\xa0 \xa0\xa0\xa0\xa0\xa0\xa0 \xa0\xa0\xa0\xa0\n\ue625\nTransactions Payment method list account\nRefunds Wire transfer tracking\nTime Sent (PST) Payment method Amount Status Action\n\ue601 …03/07/2024 20:22Credit/Debit Card\nEnd 5756 \xa0\xa0USD 1,255.50Payment Processing \xa0\nPayment is being\nprocessed, please check\nthe payment result later.\n\xa0for Initial P …\nSent Payment\n03/07/2024 20:21Payment\nProcessing\n03/07/2024 20:22Payment\nCompleted\nEstimated\nCompletion\nTime:03/07/2024\n22:22\nOperation history\n\ue625\nShanghai Beone Industrial Co., Ltd.\nContact name: \xa0Sven TANG \xa0\xa0\nRegistered\ncompany\naddress:\xa0CN,Shanghai,Shanghai,No. 5016, Wenxiang\nRoad, Xiaokunshan Town, Songjiang Dist.\nCompany tel: \xa086-021-18501768976Supplier:\nBlack Oak Essentials\nContact name: \xa0John Grattan \xa0\xa0\nRegistered company\naddress:\xa0US,California,San Diego,302 Washington St #150-\n8803 , CA 92103\nCompany tel: \xa01-707-3310347\nCompany email: \xa0whoagolly@hotmail.comBuyer:Order details\xa0\xa0\nOrder number: \xa0204243854001026990 Order Date: \xa02024-03-06 18:52:58View contractOrder amount paid: \xa0USD 0.00 \xa0\xa0 Payment records\nMessenger\n\n3/7/24, 10:23 PM Trade Assurance Order Details\nhttps://biz.alibaba.com/ta/detail.htm?spm=a2700.12336162.0.0.5c6665aaCEKIpF&orderId=204243854001026990 2/3Protections for this order \xa0\nOn-time Dispatch Guarantee \xa0\nDispatched within 30 days of payment or receive a 10% delay compensation \xa0View details\nSecure payments \xa0\nEvery payment you make on Alibaba.com is secured with strict SSL encryption and PCI DSS data protection protocols \xa0View details\nRefund policy \xa0\nClaim a refund if your order doesn't ship, is missing, or arrives with product issues \xa0View details\nAlibaba.com protects all your orders placed and paid on the platform with \xa0Company email: \xa0690725753@qq.com\nProduct Quantity 1500.00 Total Product Price USD 4,185.00Product details\nShipment terms\nPayment terms\nTrade Assurance termsNo. Product nameProduct\nimageSpec/Specs Quantity Unit Unit price Total\n1Custom logo energy saving neoprene\nterminal insulation sleeves\n- 1,500.00 Pieces USD 2.7900 USD 4,185.00\nProduct Description: 12Qt size\nShipping method Shipping fee\nExpress -\nShipment date Ship from\nShip 30 day(s) after full payment is received CN\nShipping address\n王寿铀  ,+86-15099910189, 东莞市塘厦镇  好运童园科技园南⻔进⻔右边⼆栋楼  领赫仓库 , 东莞市 , ⼴东省 ,China,000000\nTrade terms\nEXW :You need to pick up the goods from the nominated factory place, and arrange shipment by yourself, also aﬀord all the fees and risks that may occur during\ndelivery. Due to the government regulations, you need to provide cross-border logistics certiﬁcates to the seller to complete the shipment.\nPayment method Order total\nUSD 4,185.00\nInitial payment Remaining balance\nUSD 1,255.50 USD 2,929.50\nTrade Assurance\nYour actual payment will be fully covered\nIf the product quality does not match the contract or the supplier did not ship the products on time, you can request a refund within 60 days of delivery.\nOrder notes\n-\n\n3/7/24, 10:23 PM Trade Assurance Order Details\nhttps://biz.alibaba.com/ta/detail.htm?spm=a2700.12336162.0.0.5c6665aaCEKIpF&orderId=204243854001026990 3/3AliExpress  | 1688.com  | Tmall Taobao World  | Alipay  | Lazada  | Taobao Global\nBrowse Alphabetically: Onetouch  | Country Search  | Aﬃliate\nProduct Listing Policy - Intellectual Property Protection - Privacy Policy - Terms of Use - User Information Legal Enquiry Guide  - Integrity Compliance\n © 1999-2024 Alibaba.com. All rights reserved. \n  浙公⽹安备  33010002000092 号 浙B2-20120091-4Download\n"



def _doc(filename: str) -> SourceDocument:
    return SourceDocument.from_filename(filename)


def test_extract_total_order_amount_from_whsm_deposit_invoice_sub_total():
    assert extract_total_order_amount(WHSM_DEPOSIT_INVOICE_TEXT) == Decimal("13332.00")


def test_extract_total_order_amount_from_whsm_balance_invoice_total_invoice_amount():
    # A different real WHSM template era -- "Total Invoice Amount"/
    # "Total Invoice Cost" instead of "Sub Total".
    assert extract_total_order_amount(WHSM_BALANCE_INVOICE_TEXT) == Decimal("11920.00")


def test_extract_total_order_amount_from_whsm_full_invoice():
    assert extract_total_order_amount(WHSM_FULL_INVOICE_TEXT) == Decimal("343.20")


def test_extract_total_order_amount_from_sbic_order_page():
    # SBIC's "invoice" is a saved Alibaba Trade Assurance order-details
    # page, not a vendor PDF -- "Order total USD 4,185.00" is the most
    # reliable label (checked before the less-specific "Total Product
    # Price" line item subtotal).
    assert extract_total_order_amount(SBIC_ORDER_PAGE_TEXT) == Decimal("4185.00")


def test_extract_total_order_amount_none_when_table_layout_displaces_the_number():
    # Real bug found during development (2026-10-20): this real 2025
    # balance invoice's own table layout extracts with "Sub Total "
    # immediately followed by "Thanks for your business." -- the actual
    # number landed elsewhere in the text entirely (a pypdf reading-
    # order artifact on this vendor's particular table layout). Must
    # come back None (flagged), never guess at a nearby number.
    assert extract_total_order_amount(WHSM_BALANCE_INVOICE_JUMBLED_2025_TEXT) is None


def test_extract_payment_amount_from_whsm_wire_confirmation_with_no_word_boundary():
    # Real bug found during development: pypdf\'s own text runs the
    # preceding word directly into "AMOUNT$3,999.60" with no separator
    # at all ("balancAMOUNT$..."), which a \\b-anchored pattern (the
    # same shape freight_register.py\'s own _PAYMENT_AMOUNT_PATTERN
    # uses) can never match.
    assert extract_payment_amount(WHSM_DEPOSIT_PCONF_TEXT) == Decimal("3999.60")


def test_extract_payment_amount_from_sbic_credit_card_charge():
    assert extract_payment_amount(SBIC_ORDER_PAGE_TEXT) == Decimal("1255.50")


def test_extract_payment_amount_none_when_nothing_matches():
    assert extract_payment_amount("no dollar figures here at all") is None


@pytest.mark.parametrize(
    "doc_type_raw,expected",
    [
        ("bal", 1),
        ("bal2", 2),
        ("bal3", 3),
        ("bal-paid", 1),
        ("bal2-paid", 2),
        ("paid-bal", 1),
        ("1", 1),
        ("2", 2),
    ],
)
def test_balance_installment_number_finds_the_first_digit_or_defaults_to_one(doc_type_raw, expected):
    assert balance_installment_number(doc_type_raw) == expected


def test_build_components_register_rows_only_matches_an_existing_invoice_number():
    documents = [
        (_doc("2024-10-12_WHSM_Comp_INV-24Q4SLV_INV-dep.pdf"), WHSM_DEPOSIT_INVOICE_TEXT),
        (_doc("2024-10-12_WHSM_Comp_INV-24Q4SLV_pconf-dep.pdf"), WHSM_DEPOSIT_PCONF_TEXT),
    ]

    rows, unmatched = build_components_register_rows(
        documents, existing_invoice_numbers={"INV-24Q4SLV"},
    )

    assert len(rows) == 1
    assert unmatched == []
    row = rows[0]
    assert row.invoice_number == "INV-24Q4SLV"
    assert row.invoice_date == date(2024, 10, 12)
    assert row.total_order_amount == Decimal("13332.00")
    assert row.deposit_invoice_link == "2024-10-12_WHSM_Comp_INV-24Q4SLV_INV-dep.pdf"
    assert row.deposit_payment_link == "2024-10-12_WHSM_Comp_INV-24Q4SLV_pconf-dep.pdf"
    assert row.flagged is False


def test_build_components_register_rows_treats_a_genuinely_new_invoice_number_as_a_new_row():
    # Real design choice (2026-10-20): once a document's invoice number
    # neither exactly matches NOR resembles anything already in the
    # register, it's safe to auto-insert as a brand-new row -- same as
    # Freight/Overhead.
    documents = [
        (_doc("2024-10-12_WHSM_Comp_INV-24Q4SLV_INV-dep.pdf"), WHSM_DEPOSIT_INVOICE_TEXT),
    ]

    rows, unmatched = build_components_register_rows(
        documents, existing_invoice_numbers={"INV-SOMETHING-ELSE"},
    )

    assert unmatched == []
    assert len(rows) == 1
    assert rows[0].invoice_number == "INV-24Q4SLV"


def test_build_components_register_rows_reports_an_invoice_number_that_only_resembles_an_existing_one():
    # Real confirmed case (2026-10-20): a single deposit document funds
    # TWO separate final orders that already have their own register
    # rows ("INV-25Q4RPC26S-B01"/"-B02") -- the deposit's own invoice
    # number ("INV-25Q4RPC26S") is a prefix of both, so it's never
    # guessed into either an update or a brand-new row; it's reported as
    # unmatched for a human to resolve.
    documents = [
        (_doc("2025-06-05_WHSM_Comp_INV-25Q4RPC26S_INV-dep.pdf"), WHSM_DEPOSIT_INVOICE_TEXT),
    ]

    rows, unmatched = build_components_register_rows(
        documents, existing_invoice_numbers={"INV-25Q4RPC26S-B01", "INV-25Q4RPC26S-B02"},
    )

    assert rows == []
    assert len(unmatched) == 1
    assert unmatched[0].invoice_number == "INV-25Q4RPC26S"


def test_build_components_register_rows_catches_a_same_order_family_discovered_in_one_run():
    # Real confirmed case (2026-10-20): a single wire confirmation covers
    # TWO separate, genuinely new orders at once ("invoices 231201 racks
    # 2401R packaging" in its own memo text), filed under their combined
    # invoice number ("INV-USR2312-01-USPKG-2401R"). "INV-USR2312-01" and
    # "INV-USPKG-2401R" don't resemble EACH OTHER (no prefix relationship
    # at all) -- real evidence they're two distinct orders -- so both
    # become their own new row. The combined pconf's invoice number
    # resembles "INV-USR2312-01" (a prefix of it), so it's reported as
    # unmatched instead of becoming a confusing THIRD row -- a human
    # attaches it to the right order(s) by hand.
    documents = [
        (_doc("2024-01-06_WHSM_Comp_INV-USR2312-01_INV-bal.pdf"), WHSM_BALANCE_INVOICE_TEXT),
        (_doc("2024-01-06_WHSM_Comp_INV-USPKG-2401R_INV-full.pdf"), WHSM_FULL_INVOICE_TEXT),
        (_doc("2024-01-06_WHSM_Comp_INV-USR2312-01-USPKG-2401R_pconf.pdf"), WHSM_DEPOSIT_PCONF_TEXT),
    ]

    rows, unmatched = build_components_register_rows(documents, existing_invoice_numbers=set())

    assert {row.invoice_number for row in rows} == {"INV-USR2312-01", "INV-USPKG-2401R"}
    assert len(unmatched) == 1
    assert unmatched[0].invoice_number == "INV-USR2312-01-USPKG-2401R"


def test_build_components_register_rows_matches_case_insensitively():
    documents = [
        (_doc("2024-10-12_WHSM_Comp_INV-24Q4SLV_INV-dep.pdf"), WHSM_DEPOSIT_INVOICE_TEXT),
    ]

    rows, unmatched = build_components_register_rows(
        documents, existing_invoice_numbers={"inv-24q4slv"},
    )

    assert len(rows) == 1
    assert rows[0].invoice_number == "inv-24q4slv"  # canonical casing from the sheet, not the filename
    assert unmatched == []


def test_build_components_register_rows_flags_extraction_failure_but_does_not_block():
    documents = [
        (_doc("2025-07-10_WHSM_Comp_INV-25Q4RPC26S-B01_INV-bal1.pdf"), WHSM_BALANCE_INVOICE_JUMBLED_2025_TEXT),
    ]

    rows, _unmatched = build_components_register_rows(
        documents, existing_invoice_numbers={"INV-25Q4RPC26S-B01"},
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.total_order_amount is None
    assert row.flagged is True
    assert "could not extract Total Order $" in row.flag_reason
    assert "existing sheet value left as-is" in row.flag_reason
    assert row.balance_invoice_link == "2025-07-10_WHSM_Comp_INV-25Q4RPC26S-B01_INV-bal1.pdf"


def test_build_components_register_rows_flags_extraction_failure_differently_for_a_new_row():
    # A brand-new row has no existing sheet value to "leave as-is" --
    # the flag message must say so instead of implying one exists.
    documents = [
        (_doc("2025-07-10_WHSM_Comp_INV-25Q4RPC26S-B01_INV-bal1.pdf"), WHSM_BALANCE_INVOICE_JUMBLED_2025_TEXT),
    ]

    rows, _unmatched = build_components_register_rows(
        documents, existing_invoice_numbers=set(),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.total_order_amount is None
    assert row.flagged is True
    assert "could not extract Total Order $" in row.flag_reason
    assert "existing sheet value left as-is" not in row.flag_reason
    assert "fill in by hand" in row.flag_reason


def test_build_components_register_rows_sorts_numbered_balance_payments_into_their_own_slots():
    documents = [
        (_doc("2025-11-04_WHSM_Comp_INV-26Q1RCS_INV-bal1.pdf"), "balance invoice text"),
        (_doc("2025-11-04_WHSM_Comp_INV-26Q1RCS_INV-bal2.pdf"), "balance invoice text"),
        (_doc("2025-11-05_WHSM_Comp_INV-26Q1RCS_pconf-bal1.pdf"), "pconf text"),
        (_doc("2025-11-10_WHSM_Comp_INV-26Q1RCS_pconf-bal2.pdf"), "pconf text"),
        (_doc("2025-11-12_WHSM_Comp_INV-26Q1RCS_pconf-bal3.pdf"), "pconf text"),
    ]

    rows, _unmatched = build_components_register_rows(
        documents, existing_invoice_numbers={"INV-26Q1RCS"},
    )

    row = rows[0]
    assert row.balance_invoice_link == (
        "2025-11-04_WHSM_Comp_INV-26Q1RCS_INV-bal1.pdf, 2025-11-04_WHSM_Comp_INV-26Q1RCS_INV-bal2.pdf"
    )
    assert row.balance_payment_links == (
        "2025-11-05_WHSM_Comp_INV-26Q1RCS_pconf-bal1.pdf",
        "2025-11-10_WHSM_Comp_INV-26Q1RCS_pconf-bal2.pdf",
        "2025-11-12_WHSM_Comp_INV-26Q1RCS_pconf-bal3.pdf",
        "",
    )
    assert row.balance_paid_date == date(2025, 11, 12)


def test_build_components_register_rows_flags_a_refund_document():
    documents = [
        (_doc("2024-12-12_WHSM_comp_INV-24USQ4RR12C26C_INV-refund.pdf"), "refund text"),
    ]

    rows, _unmatched = build_components_register_rows(
        documents, existing_invoice_numbers={"INV-24USQ4RR12C26C"},
    )

    assert rows[0].flagged is True
    assert "refund document" in rows[0].flag_reason


def test_build_components_register_rows_flags_a_genuinely_unrecognized_doc_type():
    documents = [
        (_doc("2024-11-17_WHSM_Comp_INV-26Q1PKG_weird-suffix.pdf"), "some text"),
    ]

    rows, _unmatched = build_components_register_rows(
        documents, existing_invoice_numbers={"INV-26Q1PKG"},
    )

    assert rows[0].flagged is True
    assert "could not classify doc type" in rows[0].flag_reason


def test_build_components_register_rows_leaves_file_ids_empty_without_a_lookup():
    documents = [
        (_doc("2024-10-12_WHSM_Comp_INV-24Q4SLV_INV-dep.pdf"), WHSM_DEPOSIT_INVOICE_TEXT),
    ]

    rows, _unmatched = build_components_register_rows(
        documents, existing_invoice_numbers={"INV-24Q4SLV"},
    )

    assert rows[0].deposit_invoice_file_ids == []


def test_build_components_register_rows_populates_file_ids():
    documents = [
        (_doc("2024-10-12_WHSM_Comp_INV-24Q4SLV_INV-dep.pdf"), WHSM_DEPOSIT_INVOICE_TEXT),
    ]

    rows, _unmatched = build_components_register_rows(
        documents, existing_invoice_numbers={"INV-24Q4SLV"},
        file_ids={"2024-10-12_WHSM_Comp_INV-24Q4SLV_INV-dep.pdf": "drive-id-1"},
    )

    assert rows[0].deposit_invoice_file_ids == ["drive-id-1"]
