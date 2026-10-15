import {afterEach,describe,expect,it,vi} from "vitest";
import {DEFAULT_PREFERENCES,loadPreferences,normalizeEditorFontSize,normalizePreferences,preferenceNumber,savePreferences} from "./preferences";

afterEach(()=>vi.unstubAllGlobals());

describe("font preferences",()=>{
  it.each([13.5,"13.5","13,5"," 13,5 "])("preserves a fractional pixel value from %s",value=>{
    expect(normalizeEditorFontSize(value)).toBe(13.5);
  });
  it("uses one stable precision and clamps settings and zoom to the same bounds",()=>{
    expect(normalizeEditorFontSize(13.299999999999999)).toBe(13.3);
    expect(normalizeEditorFontSize(13.567)).toBe(13.6);
    expect(normalizeEditorFontSize(100)).toBe(32);
    expect(normalizeEditorFontSize(-2)).toBe(8);
    expect(normalizePreferences({editorFontSize:13.567}).editorFontSize).toBe(13.6);
  });
  it.each(["", " ", "NaN", "Infinity", "12px", "1,2,3", null, undefined, Number.NaN, Number.POSITIVE_INFINITY, {}])("does not turn invalid input %s into an extreme zoom",value=>{
    expect(preferenceNumber(value)).toBeUndefined();
    expect(normalizeEditorFontSize(value)).toBe(DEFAULT_PREFERENCES.editorFontSize);
    expect(normalizeEditorFontSize(value,14.5)).toBe(14.5);
  });
  it("accepts a trailing separator only when the user commits the number",()=>{
    expect(preferenceNumber("13.")).toBe(13);
    expect(preferenceNumber("13,")).toBe(13);
    expect(preferenceNumber("0")).toBe(0);
  });
  it("loads imported fractional text and persists a finite numeric preference",()=>{
    let saved=JSON.stringify({editorFontSize:"14,5",uiFontSize:"12,5",gridFontSize:"11.5"});
    vi.stubGlobal("localStorage",{getItem:()=>saved,setItem:(_key:string,value:string)=>{saved=value;}});
    const preferences=loadPreferences();
    expect(preferences).toMatchObject({editorFontSize:14.5,uiFontSize:12.5,gridFontSize:11.5});
    savePreferences(preferences);
    expect(JSON.parse(saved).editorFontSize).toBe(14.5);
    expect(loadPreferences().editorFontSize).toBe(14.5);
  });
  it("keeps counts and tab widths integral while retaining fractional font pixels",()=>{
    expect(normalizePreferences({editorFontSize:13.5,tabSize:3.5,displayRowLimit:100.5,connectionIdleSeconds:300.5})).toMatchObject({editorFontSize:13.5,tabSize:4,displayRowLimit:101,connectionIdleSeconds:301});
  });
});
