import{_ as s}from"./index.vue_vue_type_script_setup_true_lang8.js?v=1732601582185";import{_ as e}from"./index.vue_vue_type_script_setup_true_lang6.js?v=1732601582185";import{d as t,V as i,O as a,P as n,M as l,Y as c,Q as d,Z as o,R as r,ao as u}from"./vue.js?v=1732601582185";import{h as _,k as p}from"./page_layout.js?v=1732601582185";import{u as m}from"./disk.js?v=1732601582185";import{bJ as k,aV as v}from"./naive.js?v=1732601582185";import"./index.vue_vue_type_script_setup_true_lang4.js?v=1732601582185";import"./public.js?v=1732601582185";import"./common.js?v=1732601582185";import"./__commonjsHelpers__.js?v=1732601582185";const x={class:"whm-form-title"},f={class:"h-[22rem] default-disk"},g={class:""},h={class:"default-disk-info"},j={class:"disk-title"},D={class:"disk-title"},w={class:"flex"},A={class:"disk-title"},$={class:"flex w-[50rem]"},b={class:"mr-[2rem] w-[17rem]"},y={class:"flex-1"},M={class:"flex"},V={class:"disk-title"},C={class:"flex w-[50rem]"},H={class:"mr-[2rem] w-[17rem]"},I={class:"flex-1"},J={key:0,style:{color:"red"}},O={class:"whm-form-title"},P=p(t({__name:"index",setup(t){const{init:p,diskColor:P}=m(),{table:Q,loading:R,columns:Y,DefaultDisk:Z}=i(m());return p(),(t,i)=>{const p=v,m=e,q=s,z=k;return a(),n("div",null,[l(z,{class:"p-16px mb-16px"},{default:c((()=>[d("div",x,o(t.$t("Account.Disk.disk_index_763791-0")),1),d("div",f,[d("div",g,o(t.$t("Account.Disk.disk_index_763791-1")),1),d("div",h,[d("div",null,[d("span",j,o(t.$t("Account.Disk.disk_index_763791-2")),1),d("span",null,o(r(Z).mountpoint),1)]),d("div",null,[d("span",D,o(t.$t("Account.Disk.disk_index_763791-3")),1),d("span",null,o(r(Z).device),1)]),d("div",w,[d("span",A,o(t.$t("Account.Disk.disk_index_763791-4")),1),d("span",$,[d("div",b,o(r(_)(r(Z).used))+"/ "+o(r(_)(r(Z).total)),1),d("div",y,[l(p,{height:18,color:r(P)(r(Z).used_percent),percentage:Math.round(r(Z).used_percent),"indicator-placement":"inside","show-indicator":!1},null,8,["color","percentage"])])])]),d("div",M,[d("span",V,o(t.$t("Account.Disk.disk_index_763791-5")),1),d("span",C,[d("div",H,o(r(_)(r(Z).account_allocate))+"/ "+o(r(_)(r(Z).total)),1),d("div",I,[d("div",null,[l(p,{height:18,color:r(P)(r(Z).account_percent),"indicator-placement":"inside",percentage:r(Z).account_percent,"show-indicator":!1},null,8,["color","percentage"]),r(Z).account_percent>100?(a(),n("div",J,o(t.$t("Account.Disk.disk_index_763791-6")),1)):u("",!0)])])])])])]),d("div",O,o(t.$t("Account.Disk.disk_index_763791-7")),1),l(q,{feedback:!1},{table:c((()=>[l(m,{"max-height":600,loading:r(R),data:r(Q).data,columns:r(Y)},null,8,["loading","data","columns"])])),_:1})])),_:1})])}}}),[["__scopeId","data-v-cad41d95"]]);export{P as default};