import {describe,it,expect} from "vitest";
import {readNotificationFlags,saveNotificationFlags} from "./notificationPreferences";
describe("canonical notification preferences",()=>{
  it("turns flags off without resetting templates or transports",async()=>{
    const settings={enabled:true,sound:true,success_title:"{{tab_name}}",telegram:{enabled:true,chat_id:"test"}},requests:unknown[]=[];
    const transport={request:async<T>(method:string,params?:unknown)=>{requests.push({method,params});return {settings} as T;},subscribe:async()=>()=>{}};
    expect(await readNotificationFlags(transport)).toEqual({notifications:true,notificationSound:true});
    await saveNotificationFlags(transport,{notifications:false,notificationSound:false});
    expect(requests.at(-1)).toEqual({method:"notifications.settings.set",params:{settings:{...settings,enabled:false,sound:false}}});
  });
});
