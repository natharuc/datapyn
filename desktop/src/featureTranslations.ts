import { getLocale,translate } from "./i18n";
import additions from "./featureEnglish.json";
const english:Record<string,string>=additions;
const aliases:Record<string,string>={sum:"Soma",mean:"Média",min:"Mínimo",max:"Máximo",count:"Contagem",median:"Mediana",default:"Padrão",categorical:"Categórica",teal:"Verde-azulada",warm:"Quente",ocean:"Oceano"};
export function featureTranslate(source:string,variables:Record<string,string|number>={}) {
  const key=aliases[source]??source;
  const value=getLocale()==="en-US"?(english[key]??translate(key)):translate(key);
  return value.replace(/\{(\w+)\}/g,(match,key)=>key in variables?String(variables[key]):match);
}
