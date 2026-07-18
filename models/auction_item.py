from dataclasses import dataclass, field
from typing import Optional, List, Dict

@dataclass
class AuctionItem:
    case_no: str
    item_no: str
    address: str
    property_type: str
    appraisal_price: str
    minimum_bid_price: str
    auction_date: str
    status: str
    court_code: str = ""
    court_name: str = ""
    basic_info: Dict = field(default_factory=dict)
    schedule: List = field(default_factory=list)
    property_list: List = field(default_factory=list)
    appraisal_summary: str = ""
    nearby_cases: List = field(default_factory=list)
    validation_status: str = "PENDING"
    validation_reasons: List[str] = field(default_factory=list)
    crawl_date: str = ""
    has_spec_pdf: bool = False
    has_status_pdf: bool = False
    has_appraisal_pdf: bool = False
