from pydantic import BaseModel
from typing import List, Optional, Literal


ContactType = Literal["ig", "wa", "email", "tel", "website", "ppid", "pengaduan", "alamat"]


class Contact(BaseModel):
    id: str
    type: ContactType
    label: str
    value: str
    source_url: str = "manual"   # <- default
    last_verified_date: str
    notes: Optional[str] = ""



class OrgUnit(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    tasks: List[str] = []
    contact_ids: List[str] = []


# app/schemas.py
from pydantic import BaseModel
from typing import List, Literal

class DirectoryAnswer(BaseModel):
    mode: Literal["contact_lookup","org_structure","dataset_search","faq","faq_doc","not_found"]
    answer: str
    citations: List[str] = []
    followups: List[str] = []


