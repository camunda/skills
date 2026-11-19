declare module "bpmn-moddle" {
  export const BpmnModdle: any;
}
declare module "modeler-moddle/resources/modeler.json" {
  const m: any;
  export default m;
}
declare module "bpmn-js/lib/Modeler" {
  const Modeler: any;
  export default Modeler;
}
declare module "bpmn-js-properties-panel" {
  export const BpmnPropertiesPanelModule: any;
  export const BpmnPropertiesProviderModule: any;
  export const ZeebePropertiesProviderModule: any;
}
declare module "camunda-bpmn-js-behaviors/lib/camunda-cloud" {
  const m: any;
  export default m;
}
declare module "zeebe-bpmn-moddle/resources/zeebe.json" {
  const m: any;
  export default m;
}
declare module "virtual:engine-wasm" {
  /** base64 of the lean engine's .wasm */
  const b64: string;
  export default b64;
}
