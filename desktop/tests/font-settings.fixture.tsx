import React,{useState} from "react";
import {createRoot} from "react-dom/client";
import {SettingsDialog} from "../src/SettingsDialog";
import {DEFAULT_SHORTCUTS} from "../src/shortcuts";
import {loadPreferences,savePreferences} from "../src/preferences";
import {setLocale,translate} from "../src/i18n";
import "../src/styles.css";

setLocale(new URLSearchParams(location.search).get("locale")==="en-US" ? "en-US" : "pt-BR");
function Fixture(){
  const [preferences,setPreferences]=useState(loadPreferences),[saved,setSaved]=useState(0);
  Object.assign(window,{__FONT_SETTINGS_TEST__:{preferences,saved,translate,updateUnrelated:()=>setPreferences(previous=>({...previous,notifications:!previous.notifications}))}});
  return <SettingsDialog preferences={preferences} shortcuts={DEFAULT_SHORTCUTS} onClose={()=>{}} onSave={next=>{savePreferences(next);setPreferences(next);setSaved(value=>value+1);}}/>;
}
createRoot(document.getElementById("root")!).render(<Fixture/>);
