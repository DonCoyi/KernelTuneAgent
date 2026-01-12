
from enum import Enum
"""固定参数,永远存在"""
FIXED_SYSCTL_PARAMS = {
    "fs.file-max",
    "kernel.threads-max",
    "vm.watermark_scale_factor",
    "vm.dirty_background_ratio",
    "vm.dirty_expire_centisecs",
    "vm.dirty_ratio",
    "vm.dirty_writeback_centisecs",
    "vm.overcommit_memory",
    "vm.overcommit_ratio",
    "vm.page-cluster",
    "vm.swappiness",
    "transparent_hugepage",
}
"""动态参数,配置文件开关控制"""
DYNAMIC_SYSCTL_PARAMS = {
    "kernel.numa_balancing": {
        "switch": "numa"
    },
}
class ImpactLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
SYSCTL_PARAM_META = {
    "fs.file-max": {
        "range": "1000000-30000000",
        "default": "1048576",
        "step": "1000000",
        "switch": None,
        "impact": ImpactLevel.HIGH,
        "coupling": "low",
    },
    "kernel.threads-max": {
        "range": "655360-65536000",
        "default": "3092111",
        "step": "655360",
        "switch": None,
        "impact": ImpactLevel.HIGH,
        "coupling": "low",
    },
    "vm.watermark_scale_factor": {
        "range": "10-1000",
        "default": "10",
        "step": "10",
        "switch": None,
        "impact": ImpactLevel.HIGH,
        "coupling": "low",
    },
     "vm.page-cluster": {
        "range": "0-8",
        "default": "3",
        "step": "1",
        "switch": None,
        "impact": ImpactLevel.HIGH,
        "coupling": "low",
    },
    "transparent_hugepage": {
        "range": "[always,madvise,never]",
        "default": "madvise",
        "step": "1",
        "switch": None,
        "impact": ImpactLevel.HIGH,
        "coupling": "low",
    },
    "vm.dirty_background_ratio": {
        "range": "0-80",
        "default": "10",
        "step": "2",
        "switch": None,
        "impact": ImpactLevel.MEDIUM,
        "coupling": "medium",
    },
    "vm.dirty_expire_centisecs": {
        "range": "0-5000",
        "default": "3000",
        "step": "200",
        "switch": None,
        "impact": ImpactLevel.MEDIUM,
        "coupling": "medium",
    },
    "vm.dirty_ratio": {
        "range": "0-80",
        "default": "30",
        "step": "2",
        "switch": None,
        "impact": ImpactLevel.MEDIUM,
        "coupling": "medium",
    },
    "vm.dirty_writeback_centisecs": {
        "range": "100-1000",
        "default": "500",
        "step": "100",
        "switch": None,
        "impact": ImpactLevel.MEDIUM,
        "coupling": "medium",
    },
    "vm.overcommit_memory": {
        "range": "0/1/2",
        "default": "0",
        "step": "1",
        "switch": None,
        "impact": ImpactLevel.MEDIUM,
        "coupling": "medium",
    },
    "vm.overcommit_ratio": {
        "range": "0-100",
        "default": "50",
        "step": "10",
        "switch": None,
        "impact": ImpactLevel.MEDIUM,
        "coupling": "medium",
    },
    "vm.swappiness": {
        "range": "0-90",
        "default": "10",
        "step": "2",
        "switch": None,
        "impact": ImpactLevel.MEDIUM,
        "coupling": "medium",
    },
    # —— 动态参数 —— #
    "kernel.numa_balancing": {
        "range": "0-1",
        "default": "1",
        "step": "1",
        "switch": "numa",
        "impact": ImpactLevel.MEDIUM,
        "coupling": "medium",
    },
}

"""调优阶段"""
class Phase(Enum):
    EXPLORATION = ("exploration", 0.20, 5, False, "大范围探索", ImpactLevel.HIGH)
    EXPLOITATION = ("exploitation", 0.08, 3, False, "围绕有效方向收敛", ImpactLevel.MEDIUM)
    REFINEMENT = ("refinement", 0.02, 1, False, "小范围精调", ImpactLevel.LOW)

    def __init__(
        self,
        value_str: str,
        min_change_ratio: float,
        min_changed_params: int,
        allow_float: bool,
        desc: str,
        impact: str
    ):
        self._value_ = value_str
        self.min_change_ratio = min_change_ratio
        self.min_changed_params = min_changed_params
        self.allow_float = allow_float
        self.desc = desc
        self.impact = impact  # 👈 新增属性

    @classmethod
    def from_string(cls, s: str):
        """根据字符串值（如 'exploration'）返回对应的 Phase 枚举"""
        for phase in cls:
            if phase.value == s:
                return phase
        raise ValueError(f"Unknown phase string: {s}")

    def __str__(self):
        return self.value

    def __repr__(self):
        return f"<Phase.{self.name}: '{self.value}', impact={self.impact}>"
