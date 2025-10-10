def calculator(x : int , y : int , delta : str) -> float:
    if delta == "+" :
        return x+y
    elif delta == "-" :
        return x-y
    
def search(x):
    return None
def rag(x):
    return None

def diag_query(query : str) :
    
    return 0

def agent_planner(query : str ) -> dict[str, any]  :
    registed_tools = ["calculator", "rag", "search"]
    tool_result = []
    for tool in registed_tools :
        if tool in query :
            tool_result.append(tool)
    return tool_result

def agent_excutor(tool_list : list) :
    
    for tool in tool_list :
        if tool == "calculator" :
