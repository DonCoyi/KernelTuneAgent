"""生成系统提示词和反馈提示词"""
from pydantic import BaseModel, create_model
from typing import Dict, Any
from enum import Enum
from KernelTuneAgent.config import FIXED_SYSCTL_PARAMS,Phase,DYNAMIC_SYSCTL_PARAMS,SYSCTL_PARAM_META

class PromptBuilder:
    def __init__(self, config_path: str = "./sys.config"):
        self.config_path = config_path
        self.sys_cfg = self._load_sys_config()
        #self.SysctlConfig = self._build_sysctl_config()
        self.param_info = self._build_param_info()
        self.target= 0.08
    # TODO:读取所有实验环境、路径信息
    def _load_sys_config(self) -> Dict[str, bool]:
        """从配置文件加载参数开关"""
        cfg = {}
        try:
            with open(self.config_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    key, value = line.split(":", 1)
                    cfg[key.strip()] = value.strip().lower() == "true"
        except FileNotFoundError:
            print(f"Warning: {self.config_path} not found. Using empty config.")
        return cfg

    def _collect_sysctl_fields(self) -> Dict[str, tuple]:
        fields = {}

        # 固定参数：无条件加入
        for name in FIXED_SYSCTL_PARAMS:
            fields[name] = (int, ...)

        # 动态参数：由 sys.config 控制
        for name, spec in DYNAMIC_SYSCTL_PARAMS.items():
            if self.sys_cfg.get(spec["switch"], False):
                fields[name] = (int, ...)

        return fields

    #def _build_sysctl_config(self):
    #    fields = self._collect_sysctl_fields()
    #    model_name = f"SysctlConfig_{hash(frozenset(self.sys_cfg.items()))}"
    #    return create_model(model_name, **fields, __base__=BaseModel)

    def _build_param_info(self) -> str:
        lines = []
        for name, meta in SYSCTL_PARAM_META.items():
            sw = meta.get("switch")
            if sw is not None and not self.sys_cfg.get(sw, False):
                continue
            line = (
                f"{name}: range {meta['range']}, "
                f"default {meta['default']}, "
                f"step {meta['step']}, "
                f"impact {meta['impact']}, " 
                f"coupling {meta['coupling']}." 
            )
            lines.append(line)
        return "\n".join(lines)
    def get_param_info(self) -> str:
        """返回当前启用的 sysctl 参数描述信息（多行字符串）"""
        return self.param_info

    # TODO:改成动态加载
    def build_system_prompt_messages(self) -> str:
        """构建第一轮推荐 sysctl 配置的 prompt（用于获取 baseline）"""
        content = (
            f"""
                根据实验环境推荐 sysctl 配置,可以使用各种工具来完成任务。

                【可用工具】
                    python_execute: 执行Python代码
                    file_editor: 读写文件和查看目录
                    bash_execute: 执行命令行命令

                【实验环境】
                    CPU: 48 cores
                    内存: 366GB
                    磁盘: 250GB SSD
                    操作系统: Ubuntu 22.04
                    深度学习模型: ResNet50

                【常用命令】
                    运行训练命令: python /root/dongjing/model/resnet50.py
                    获取日志信息命令: grep "平均训练耗时:" /root/dongjing/result.log && rm -f /root/dongjing/result.log
                    修改参数命令:    sysctl -w [param_name]=xxx # 除了transparent_hugepage的参数
                                    echo always > /sys/kernel/mm/transparent_hugepage/enabled # 0:always,1:madvise;2:never
                    
                【可调参数详情】
                    {self.get_param_info()}

            """
        )
        return content
    def build_feedback_prompt(phase: Phase, baseline: float, last_value=None) -> str:
        """性能反馈的 prompt 构建"""
        perf_desc = ""
        failure_rule = ""
    
        if last_value is not None:
            diff = (last_value - baseline) / baseline * 100
            if diff > 0:
                perf_desc = f"上一轮比 baseline 慢了 {diff:.2f}%"
                failure_rule = (
                "- 上一轮参数组合未带来性能提升，视为失败方案，本轮避免返回与上一轮相似的配置\n"
                )
            else:
                perf_desc = f"上一轮比 baseline 快了 {abs(diff):.2f}%"

        return (
            f"【用户请求】"
            f"根据调优阶段规则进行参数推荐，每个字段以 'key: value' 格式返回，通过命令行修改所有参数取值为推荐值，跑一次模型，读取日志文件\n"
            f"【阶段规则】\n"
            f"- 当前阶段 {phase.value}, {phase.desc}"
            f"- 优先调整impact为 {phase.impact} 的参数\n"
            f"- 至少调整 {phase.min_changed_params} 个参数\n"
            f"- 调整幅度至少为 {phase.min_change_ratio}\n"
            f"【性能反馈】\n"
            f"baseline: {baseline:.4f} 秒\n"
            f"{perf_desc}\n\n"
            f"{failure_rule}\n\n"
        )
    
    #def get_config_model(self):
     #   """返回动态生成的 Pydantic 模型，可用于校验 LLM 输出"""
      #  return self.SysctlConfig

    #def get_active_param_names(self) -> list[str]:
    #    """返回当前启用的参数名列表"""
    #    return list(self.SysctlConfig.model_fields.keys())


