"""風控參數 API — 讀取與更新"""

import json
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException

from api.deps import get_db
from database.db_manager import DatabaseManager

router = APIRouter()


@router.get("")
def get_params(db: DatabaseManager = Depends(get_db)):
    """取得所有風控參數"""
    return db.get_risk_params()


@router.get("/presets")
def get_presets():
    """取得預設方案列表（從 risk_defaults.json）"""
    p = Path(__file__).resolve().parent.parent.parent / "config" / "risk_defaults.json"
    if not p.exists():
        return {"presets": {}, "active_preset": None}
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "presets": data.get("presets", {}),
        "active_preset": data.get("active_preset"),
    }


@router.put("/{param_name}")
def set_param(
    param_name: str,
    body: dict = Body(...),
    db: DatabaseManager = Depends(get_db),
):
    """更新單一風控參數。body: { "value": <any>, "changed_by": "dashboard" }"""
    value = body.get("value")
    if value is None:
        raise HTTPException(status_code=400, detail="Missing 'value' in body")
    changed_by = body.get("changed_by", "dashboard")
    db.set_risk_param(param_name, value, changed_by=changed_by)
    return {"param_name": param_name, "value": value}


@router.post("/load-preset")
def load_preset(
    body: dict = Body(...),
    db: DatabaseManager = Depends(get_db),
):
    """載入預設方案。body: { "preset": "conservative" | "moderate" | "aggressive" }"""
    preset = body.get("preset")
    if preset not in ("conservative", "moderate", "aggressive"):
        raise HTTPException(status_code=400, detail="preset must be conservative, moderate, or aggressive")
    p = Path(__file__).resolve().parent.parent.parent / "config" / "risk_defaults.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="risk_defaults.json not found")
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get("presets", {}).get(preset)
    if not raw:
        raise HTTPException(status_code=404, detail=f"Preset {preset} not found")
    presets = dict(raw)
    label = presets.pop("label", preset)
    for name, value in presets.items():
        db.set_risk_param(name, value, changed_by=f"preset_{preset}")
    db.set_risk_param("active_preset", preset, changed_by="dashboard")
    return {"loaded": preset, "label": label}
