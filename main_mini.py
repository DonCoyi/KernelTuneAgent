"""
KernelTuneAgent 主运行文件
"""
import asyncio
from KernelTuneAgent import KernelTuneAgent
from KernelTuneAgent.llm import SimpleLLM


async def main():
    """主函数"""
    # 从环境变量获取API密钥
    # api_key = os.getenv("OPENAI_API_KEY")
    # api_key = "your api key"
    # if not api_key:
    """     print("❌ 请设置环境变量 OPENAI_API_KEY")
        print("   export OPENAI_API_KEY='你的API密钥'")
        return """
    
    # 创建LLM实例
    llm = SimpleLLM(
        # api_key=api_key,
        model="output/qwen3_lora",  # 本地模型
        base_url="http://localhost:8001/v1"
    )
    
    # 创建代理
    agent = KernelTuneAgent(
        llm=llm,
        name="KernelTuneAgent",
        max_steps=10
    )
    
    print("🤖 KernelTuneAgent 已启动!")
    print("💡 该Agent帮助你找到训练模型的最佳内核参数配置")
    print("- 在正式开始之前首先完成配置文件的更改，使其适配自己的环境")
    input("👉 按 Enter 键继续...")

    # 交互循环
    while True:
        try:
            
            # 执行任务
            # 连续执行，不需要用户输入
            result = await agent.run()
            print(f"\n📋 执行结果:\n{result}")
            
        except KeyboardInterrupt:
            print("\n👋 程序被中断，再见!")
            break
        except Exception as e:
            print(f"❌ 发生错误: {e}")


if __name__ == "__main__":
    asyncio.run(main())