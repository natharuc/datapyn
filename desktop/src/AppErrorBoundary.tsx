import { Component,type ReactNode } from "react";
import { copySupportReport,saveSupportReport,type IncidentKind } from "./supportDiagnostics";
import { featureTranslate as t } from "./featureTranslations";
import "./supportDiagnostics.css";

interface Props {children:ReactNode;onReload?:()=>void|Promise<void>}
interface State {failed:boolean;kind:IncidentKind;busy:boolean;message:string}
export class AppErrorBoundary extends Component<Props,State> {
  state:State={failed:false,kind:"react_render",busy:false,message:""};
  static getDerivedStateFromError(){return{failed:true,kind:"react_render"};}
  // Exception messages/stacks can contain SQL, Python, paths or credentials.
  // Reports intentionally retain only the event category.
  componentDidCatch(){/* No exception text is logged or transmitted. */}
  private error=()=>this.setState({failed:true,kind:"javascript_error"});
  private rejection=()=>this.setState({failed:true,kind:"unhandled_rejection"});
  componentDidMount(){window.addEventListener("error",this.error);window.addEventListener("unhandledrejection",this.rejection);}
  componentWillUnmount(){window.removeEventListener("error",this.error);window.removeEventListener("unhandledrejection",this.rejection);}
  private async report(save:boolean){this.setState({busy:true,message:""});try{const result=save?await saveSupportReport(this.state.kind):await copySupportReport(this.state.kind);if(result)this.setState({message:t(save?"Diagnóstico salvo.":"Diagnóstico copiado.")});}catch{this.setState({message:t("Não foi possível obter o diagnóstico. Tente reabrir o aplicativo.")});}finally{this.setState({busy:false});}}
  private async reload(){this.setState({busy:true});try{if(this.props.onReload)await this.props.onReload();else window.location.reload();}catch{this.setState({busy:false,message:t("Não foi possível reabrir o aplicativo.")});}}
  render(){if(!this.state.failed)return this.props.children;return <main className="app-crash-screen" role="alert"><div><span className="app-crash-label">DataPyn</span><h1>{t("A interface encontrou um erro.")}</h1><p>{t("Reabra o aplicativo para recuperar as análises salvas automaticamente.")}</p><p className="app-crash-note">{t("Você pode salvar um diagnóstico com versões e informações do sistema, sem código, dados ou credenciais.")}</p><div className="app-crash-actions"><button className="primary-button" disabled={this.state.busy} onClick={()=>void this.reload()}>{t("Reabrir aplicativo")}</button><button disabled={this.state.busy} onClick={()=>void this.report(true)}>{t("Salvar diagnóstico")}</button><button disabled={this.state.busy} onClick={()=>void this.report(false)}>{t("Copiar diagnóstico")}</button></div>{this.state.message&&<p className="app-crash-message">{this.state.message}</p>}</div></main>;}
}
