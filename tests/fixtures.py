import copy
from jev_prune.core import MODEL
TEXT = "An immutable fixture file contains the same verified text. " * 24


def pi_messages():
    return [{"role":"user", "content":"Read the fixture."},
            {"role":"assistant", "content":[{"type":"toolCall","id":"a","name":"read","arguments":{"path":"fixture.txt"}}]},
            {"role":"toolResult","toolCallId":"a","toolName":"read","content":[{"type":"text","text":TEXT}],"isError":False},
            {"role":"assistant", "content":[{"type":"toolCall","id":"b","name":"read","arguments":{"path":"fixture.txt"}}]},
            {"role":"toolResult","toolCallId":"b","toolName":"read","content":[{"type":"text","text":TEXT}],"isError":False},
            {"role":"user", "content":"Continue the fixture task; keep all constraints."},
            *[{"role":"assistant","content":[{"type":"text","text":f"Progress {i}"}]} for i in range(20)]]


def openai_messages():
    out = []
    for m in pi_messages():
        if m["role"] == "toolResult":
            out.append({"role":"tool","tool_call_id":m["toolCallId"],"content":TEXT})
        elif m["role"] == "assistant" and m["content"][0]["type"] == "toolCall":
            c=m["content"][0]
            out.append({"role":"assistant","content":None,"tool_calls":[{"type":"function","id":c["id"],"function":{"name":"read_file","arguments":'{"path":"fixture.txt"}'}}]})
        else: out.append(copy.deepcopy(m))
    return out


def opencode_messages():
    out=[]
    for i,m in enumerate(pi_messages()):
        info={"id":f"msg{i}","sessionID":"s","role":"assistant" if m["role"]=="toolResult" else m["role"]}
        if m["role"]=="toolResult":
            parts=[{"id":m["toolCallId"],"type":"tool","callID":m["toolCallId"],"tool":"read","state":{"status":"completed","input":{"filePath":"fixture.txt"},"output":TEXT}}]
        elif isinstance(m["content"],str): parts=[{"type":"text","text":m["content"]}]
        else: parts=[{"type":"text","text":"Other assistant content"}]
        out.append({"info":info,"parts":parts})
    return out


def yes(body):
    return {"model":MODEL,"answers":{k:{"type":"noul","noul":1.0 if k.endswith("coverage") else 0.0} for k in body["questions"]},"usage":{"input_tokens":1,"output_tokens":1}}
