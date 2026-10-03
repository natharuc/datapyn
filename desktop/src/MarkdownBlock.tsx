import { useState } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
export function MarkdownBlock({ code, onChange, raw = false }: {code:string;onChange:(code:string)=>void;raw?:boolean}) {
  const [editing,setEditing]=useState(false);
  return <div className="markdown-block"><button className="text-button" onClick={()=>setEditing(!editing)}>{editing ? "Visualizar" : "Editar"} {raw ? "texto" : "Markdown"}</button>{editing ? <textarea value={code} onChange={e=>onChange(e.target.value)}/> : raw ? <pre>{code}</pre> : <div className="markdown-preview" dangerouslySetInnerHTML={{__html:DOMPurify.sanitize(marked.parse(code) as string)}}/>}</div>;
}
