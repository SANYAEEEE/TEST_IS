"""Deterministic, fail-closed grading of the 20.11 question bank.

Never executes student-supplied commands/code or uses fuzzy string matching.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from ipaddress import ip_address, ip_network
import json
import re
import unicodedata

MAX_ANSWER = 256
# A space is accepted only as a strict thousands separator (groups of three).
NUMBER = re.compile(
    r'^([+-]?(?:(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)\s*(.*?)$',
    re.S,
)

def normalize(s: str, *, punctuation: bool = False) -> str:
    s = unicodedata.normalize('NFKC', s).strip().casefold().replace('ё','е')
    s = re.sub(r'\s+', ' ', s)
    return re.sub(r'[.?!]+$', '', s).strip() if punctuation else s

@lru_cache(maxsize=4096)
def compile_spec(json_spec: str) -> tuple:
    """Validate trusted answer metadata once per unique spec, cache all accepted forms."""
    spec = json.loads(json_spec)
    kind = spec.get('kind')
    if kind not in {'number','text','token','ipv4','ipv6','cidr4','cidr6'}:
        raise ValueError('Unknown input kind')
    if kind == 'number':
        val=Decimal(str(spec['expected']))
        tol=Decimal(str(spec.get('abs_tolerance',0)))
        if not val.is_finite() or not tol.is_finite() or tol<0:
            raise ValueError('Invalid numeric spec')
        aliases=spec.get('unit_aliases',[])
        if not isinstance(aliases,list) or any(not isinstance(a,str) for a in aliases):
            raise ValueError('unit_aliases must be strings')
        return kind, val, tol, frozenset(normalize(s) for s in aliases), bool(spec.get('require_unit',False))
    accepted=spec['accepted']
    if not isinstance(accepted,list) or not accepted or any(not isinstance(s,str) or not s.strip() for s in accepted):
        raise ValueError('Empty accepted values')
    if kind=='text':
        strip=bool(spec.get('strip_terminal_punct',True))
        return kind, frozenset(normalize(s,punctuation=strip) for s in accepted),strip
    if kind=='token':
        case=bool(spec.get('case_sensitive',False))
        transform=lambda s: unicodedata.normalize('NFKC',s).strip() if case else unicodedata.normalize('NFKC',s).strip().casefold()
        return kind,frozenset(transform(s) for s in accepted),case
    ipv=6 if kind.endswith('6') else 4
    net=kind.startswith('cidr')
    parsed=[]
    for x in accepted:
        v=ip_network(x,strict=True) if net else ip_address(x)
        if v.version!=ipv: raise ValueError('Incorrect IP family')
        parsed.append(v)
    return kind,frozenset(parsed),ipv

def evaluate_input(spec:dict, answer:str) -> bool:
    if not isinstance(answer,str) or not 0<len(answer)<=MAX_ANSWER or not answer.strip():
        return False
    try:
        kind,*rest=compile_spec(json.dumps(spec,ensure_ascii=False,sort_keys=True,separators=(',',':')))
        if kind=='number':
            expected,tolerance,aliases,require_unit=rest
            m=NUMBER.fullmatch(unicodedata.normalize('NFKC',answer.strip()))
            if m is None:return False
            number,unit=m.groups()
            if ',' in number and '.' in number: return False
            actual=Decimal(number.replace(' ','').replace('\u00a0','').replace('\u202f','').replace(',','.'))
            if not actual.is_finite():return False
            if unit:
                if not aliases or normalize(unit) not in aliases:return False
            elif require_unit:return False
            return abs(actual-expected)<=tolerance
        if kind=='text':
            accepted,strip=rest
            return normalize(answer,punctuation=strip) in accepted
        if kind=='token':
            accepted,case=rest
            val=unicodedata.normalize('NFKC',answer).strip()
            return (val if case else val.casefold()) in accepted
        accepted,version=rest
        val=ip_network(answer.strip(),strict=True) if kind.startswith('cidr') else ip_address(answer.strip())
        return val.version==version and val in accepted
    except (ValueError,TypeError,OverflowError,InvalidOperation,KeyError,ArithmeticError):
        return False

def check_answer(q:dict, answer) -> bool:
    kind=q['type']
    if kind=='input':return evaluate_input(q['input_spec'],answer)
    if kind in ('single','multi','case'):
        if not isinstance(answer,list) or not all(isinstance(x,str) for x in answer):return False
        return (len(answer)==len(set(answer)) and set(answer)==set(q['correct']) and set(answer)<=set(q['options']))
    if kind=='ordering':return isinstance(answer,list) and answer==q['correct']
    if kind=='matching':return isinstance(answer,dict) and answer==q['correct']
    return False

VISIBLE = ('id','topic','subtopic','type','difficulty','points','question','options','scenario','left','right','image','image_alt','input_hint')
def public_question(q:dict)->dict:
    return {key:q[key] for key in VISIBLE if key in q}

def validate_bank(qs:list[dict]):
    """Fail at startup on malformed or unverifiable assessment keys."""
    ids=set()
    for q in qs:
        id=q['id']
        if id in ids:raise ValueError(f'Duplicate question ID {id}')
        ids.add(id)
        kind=q['type']
        if kind=='input':
            compile_spec(json.dumps(q['input_spec'],ensure_ascii=False,sort_keys=True,separators=(',',':')))
            if not evaluate_input(q['input_spec'],q['correct'][0]):
                raise ValueError(f'Self-test of expected input failed at {id}')
        elif kind in ('single','multi','case'):
            correct=q['correct'];options=q['options']
            if len(options)!=len(set(options)) or not correct or not set(correct)<=set(options):
                raise ValueError(f'Invalid options or key at {id}')
            if kind=='single' and len(correct)!=1:
                raise ValueError(f'Wrong single-key size {id}')
        elif kind=='matching':
            if set(q['correct'])!=set(q['left']) or set(q['correct'].values())!=set(q['right']):
                raise ValueError(f'Bad matching spec at {id}')
        elif kind=='ordering':
            if set(q['correct'])!=set(q['options']) or len(q['correct'])!=len(q['options']):
                raise ValueError(f'Bad ordering spec at {id}')
        else:raise ValueError(f'Unsupported kind {kind} at {id}')
