"""Measure actual autocomplete RPC latency with a private SQLite/namespace fixture."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time

from smoke_runtime import RuntimeClient


def summary(values):
    ordered=sorted(values)
    return {"samples":len(values),"p50_ms":round(statistics.median(ordered),3),
            "p95_ms":round(ordered[min(len(ordered)-1,int(len(ordered)*.95))],3),"max_ms":round(max(ordered),3)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable",help="Frozen datapyn-runtime.exe; omit for checkout Python")
    parser.add_argument("--samples",type=int,default=40)
    options=parser.parse_args()
    if not 5<=options.samples<=1000:parser.error("samples must be between 5 and 1000")
    with tempfile.TemporaryDirectory(prefix="datapyn-completion-bench-") as temporary:
        root=Path(temporary)
        os.environ.update(DATAPYN_RUNTIME_STATE_PATH=str(root/"state"),DATAPYN_WORKSPACE_PATH=str(root/"state"),
                          DATAPYN_RUNTIME_DATA_DIR=str(root/"packages"),DATAPYN_SNAPSHOT_ROOT=str(root/"snapshots"))
        database=root/"sample.sqlite"
        with sqlite3.connect(database) as db:db.execute("CREATE TABLE sample(id INTEGER, title TEXT)")
        db.close()
        (root/"state").mkdir()
        (root/"state"/"connections.json").write_text(json.dumps({"version":1,"groups":[],"connections":[{
            "id":"benchmark-sqlite","name":"Benchmark SQLite","group_id":None,"favorite":False,"order":0,
            "config":{"db_type":"sqlite","database":str(database)},"has_password":False}]}),encoding="utf-8")
        client=RuntimeClient(options.executable,30)
        try:
            client.request("session.create",{"session_id":"benchmark"})
            client.event("session.ready",session_id="benchmark")
            client.request("connection.connect",{"session_id":"benchmark","connection_id":"benchmark-sqlite"})
            sequence=0
            def completion(code,language="python",**kwargs):
                nonlocal sequence
                sequence+=1
                params={"session_id":"benchmark","connection_id":"benchmark-sqlite","block_id":"benchmark-editor","completion_id":f"measure-{sequence}",
                        "language":language,"code":code,"line":1,"column":len(code.encode("utf-16-le"))//2+1,**kwargs}
                start=time.perf_counter();result=client.request("language.complete",params)
                return (time.perf_counter()-start)*1000,result
            first,python=completion("pd.Dat",global_imports="import pandas as pd")
            assert "DataFrame" in {i["label"] for i in python["items"]},python
            client.execute("benchmark","namespace","python","df = pd.DataFrame({'sales_total':[1], 'sales total':[2]})")
            client.wait(lambda item:item.get("event")=="language.context_updated" and "df" in item.get("payload",{}).get("variables",{}))
            column_latency,columns=completion('df["sales ')
            assert {i["label"] for i in columns["items"]}=={"sales total"},columns
            python_warm=[]
            first_method,_=completion("df.qu")
            for _ in range(options.samples):
                duration,result=completion("df.qu")
                assert "query" in {i["label"] for i in result["items"]},result
                python_warm.append(duration)
            sql_code="SELECT s.ti FROM main.sample s"
            start=time.perf_counter();completion(sql_code,"sql",column=12)
            client.wait(lambda item:item.get("event")=="language.context_updated" and "main.sample" in item.get("payload",{}).get("schema_snapshot",{}).get("columns",{}))
            schema_latency=(time.perf_counter()-start)*1000
            sql_warm=[]
            for _ in range(options.samples):
                duration,result=completion(sql_code,"sql",column=12)
                assert "title" in {i["label"] for i in result["items"]},result
                sql_warm.append(duration)
            print(json.dumps({"mode":"frozen" if options.executable else "source","python_first_ms":round(first,3),
                              "dataframe_method_first_ms":round(first_method,3),"dataframe_string_column_ms":round(column_latency,3),"sqlite_schema_ready_ms":round(schema_latency,3),
                              "python_rpc":summary(python_warm),"sql_rpc":summary(sql_warm)},ensure_ascii=False))
        finally:client.close()


if __name__=="__main__":main()
