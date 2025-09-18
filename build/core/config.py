# -*- coding: utf-8 -*-
from __future__ import annotations
import yaml
from dataclasses import dataclass, field
from typing import Any, Dict

@dataclass
class Config:
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        return cls(d)

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def section(self, name: str) -> Dict[str, Any]:
        return dict(self.data.get(name, {}))
