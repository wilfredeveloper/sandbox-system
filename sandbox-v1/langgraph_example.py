"""
LangGraph Integration Example
Shows how to create a simple agent that uses the sandbox
"""

from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from sandbox_client import SandboxClient
import operator

# Define the state
class AgentState(TypedDict):
    messages: Annotated[list[str], operator.add]
    command: str
    output: str
    session_id: str

# Global sandbox client (in practice, manage this per user)
sandbox_client = SandboxClient(server_url="http://localhost:5000")

def create_sandbox_node(state: AgentState) -> AgentState:
    """Create a sandbox session"""
    session_id = sandbox_client.create_session()
    return {
        "messages": ["Sandbox session created"],
        "session_id": session_id
    }

def execute_command_node(state: AgentState) -> AgentState:
    """Execute a command in the sandbox"""
    command = state.get("command", "echo 'No command provided'")
    
    try:
        result = sandbox_client.execute(command)
        output = result['output']
        exit_code = result['exit_code']
        
        return {
            "messages": [f"Executed: {command}"],
            "output": output
        }
    except Exception as e:
        return {
            "messages": [f"Error: {str(e)}"],
            "output": ""
        }

def cleanup_sandbox_node(state: AgentState) -> AgentState:
    """Cleanup the sandbox"""
    sandbox_client.cleanup()
    return {
        "messages": ["Sandbox cleaned up"]
    }

# Build the graph
def create_sandbox_agent():
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("create_sandbox", create_sandbox_node)
    workflow.add_node("execute_command", execute_command_node)
    workflow.add_node("cleanup", cleanup_sandbox_node)
    
    # Add edges
    workflow.set_entry_point("create_sandbox")
    workflow.add_edge("create_sandbox", "execute_command")
    workflow.add_edge("execute_command", "cleanup")
    workflow.add_edge("cleanup", END)
    
    return workflow.compile()

# Example usage
if __name__ == "__main__":
    agent = create_sandbox_agent()
    
    # Run the agent
    initial_state = {
        "messages": [],
        "command": "ls -la && echo 'Hello from LangGraph sandbox!' && python3 --version",
        "output": "",
        "session_id": ""
    }
    
    result = agent.invoke(initial_state)
    
    print("\n=== Agent Execution Results ===")
    print("Messages:", result["messages"])
    print("\nCommand Output:")
    print(result["output"])


# More Advanced Example: Multi-step execution
def create_multi_step_agent():
    """Agent that can execute multiple commands in sequence"""
    
    class MultiStepState(TypedDict):
        commands: list[str]
        current_index: int
        outputs: list[str]
        session_id: str
    
    def setup_node(state: MultiStepState) -> MultiStepState:
        session_id = sandbox_client.create_session()
        return {
            "session_id": session_id,
            "current_index": 0,
            "outputs": []
        }
    
    def execute_node(state: MultiStepState) -> MultiStepState:
        commands = state["commands"]
        index = state["current_index"]
        
        if index < len(commands):
            result = sandbox_client.execute(commands[index])
            return {
                "outputs": [result["output"]],
                "current_index": index + 1
            }
        return {}
    
    def should_continue(state: MultiStepState) -> str:
        if state["current_index"] < len(state["commands"]):
            return "execute"
        return "cleanup"
    
    def cleanup_node(state: MultiStepState) -> MultiStepState:
        sandbox_client.cleanup()
        return {}
    
    workflow = StateGraph(MultiStepState)
    workflow.add_node("setup", setup_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("cleanup", cleanup_node)
    
    workflow.set_entry_point("setup")
    workflow.add_edge("setup", "execute")
    workflow.add_conditional_edges(
        "execute",
        should_continue,
        {
            "execute": "execute",
            "cleanup": "cleanup"
        }
    )
    workflow.add_edge("cleanup", END)
    
    return workflow.compile()


# Test multi-step agent
if __name__ == "__main__":
    print("\n\n=== Multi-Step Agent Example ===")
    
    multi_agent = create_multi_step_agent()
    
    result = multi_agent.invoke({
        "commands": [
            "echo 'Step 1: Create a file'",
            "echo 'Hello World' > test.txt",
            "cat test.txt",
            "ls -la test.txt"
        ],
        "current_index": 0,
        "outputs": [],
        "session_id": ""
    })
    
    print("\nMulti-step outputs:")
    for i, output in enumerate(result["outputs"], 1):
        print(f"\nStep {i}:")
        print(output)
