import {errorText,isRuntimeErrorInfo,RuntimeRequestError,type RuntimeErrorInfo} from "./runtime";

/** Older runtimes can still return a traceback as their whole error message. */
export function technicalErrorText(text:string):boolean {
  return /Traceback \(most recent call last\)|\n\s*File ".*", line \d+|\[SQL:|\[parameters:|sqlalche\.me\/e\/|sqlalchemy\.exc\.|^\s*\(?['"][0-9A-Z]{5}['"]/i.test(text);
}

export function errorInfoFor(error:unknown,title="Falha na execução"):RuntimeErrorInfo {
  if(error instanceof RuntimeRequestError && error.errorInfo)return error.errorInfo;
  if(isRuntimeErrorInfo(error))return error;
  if(error && typeof error==="object" && "error_info" in error && isRuntimeErrorInfo(error.error_info))return error.error_info;
  let text="";try{text=errorText(error)??"";}catch{/* An unserializable rejection still gets a usable summary. */}
  const details=text.trim().slice(0,32768);
  const message=!technicalErrorText(details) && details.length<=600?details:"Não foi possível concluir a operação. Consulte os detalhes técnicos.";
  return {category:"internal",title,message:message||title,...(details&&details!==message?{technical_details:details}:{})};
}

export function errorDetailsText(info:RuntimeErrorInfo):string {
  return [info.title,info.message,info.technical_details].filter(Boolean).join("\n\n");
}
