System.register(["./index-legacy102.js?v=1732601582185","./page_layout-legacy.js?v=1732601582185","./index-legacy.js?v=1732601582185","./index.vue_vue_type_script_setup_true_lang-legacy8.js?v=1732601582185","./index.vue_vue_type_script_setup_true_lang-legacy6.js?v=1732601582185","./public-legacy.js?v=1732601582185","./alarm-legacy.js?v=1732601582185","./vue-legacy.js?v=1732601582185","./index.vue_vue_type_script_setup_true_lang-legacy9.js?v=1732601582185","./naive-legacy.js?v=1732601582185","./common-legacy.js?v=1732601582185","./__commonjsHelpers__-legacy.js?v=1732601582185","./index.vue_vue_type_script_setup_true_lang-legacy4.js?v=1732601582185"],(function(e,t){"use strict";var n,a,i,l,o,s,d,r,c,m,u,g,p,_,f,x,h,C,w,y,b,k,v,A,j,L,z,M,P,W,$,R,E,T,U,H,B,S,I,O,D,V,F,J,Q,X,Y,Z,q,G,K,N,ee,te,ne,ae,ie;return{setters:[e=>{n=e._},e=>{a=e.i,i=e.I,l=e.k,o=e.S,s=e.a7,d=e.o,r=e.f,c=e.c,m=e.j,u=e.a4},e=>{g=e._},e=>{p=e._},e=>{_=e._},e=>{f=e.d,x=e.f,h=e.u,C=e.a,w=e.h,y=e.i},e=>{b=e.c,k=e.d,v=e.e,A=e.f,j=e.s,L=e.h,z=e.b,M=e.o,P=e.i},e=>{W=e.r,$=e.d,R=e.t,E=e.W,T=e.e,U=e.M,H=e.O,B=e.P,S=e.Q,I=e.Z,O=e.R,D=e.X,V=e.F,F=e.j,J=e.ak,Q=e.Y,X=e.c,Y=e.o,Z=e.a6,q=e.ad,G=e.n,K=e.f,N=e.ac},e=>{ee=e._},e=>{te=e.bR,ne=e.bp,ae=e.aa,ie=e.bJ},null,null,null],execute:function(){var le=document.createElement("style");le.textContent=".alarm-info+.alarm-info[data-v-23d9e8a8]{margin-top:20px}.alarm-title[data-v-23d9e8a8]{margin-bottom:10px;font-size:14px;font-weight:700}.alarm-box[data-v-23d9e8a8]{max-height:200px;overflow-y:auto;border-radius:4px;--un-bg-opacity:1;background-color:rgb(245 245 245 / var(--un-bg-opacity));padding:16px;line-height:22px;border:1px solid #ececec}.icon[data-v-70f7d608]{width:36px;height:36px;margin-right:8px;background:url(/static/vite/images/alarm.png);background-size:100%;border-radius:6px}.icon.mail[data-v-70f7d608]{background-position:0 36px}.icon.dingding[data-v-70f7d608]{background-position:0 0}.icon.feishu[data-v-70f7d608]{background-position:0 144px}.icon.weixin[data-v-70f7d608]{background-position:0 72px}.icon.tg[data-v-70f7d608]{background-position:0 180px}\n",document.head.appendChild(le);const oe=W([]),se=new Map([["mail",a.global.t("Config.Alarm.index_3")],["feishu",a.global.t("Config.Alarm.index_4")],["dingding",a.global.t("Config.Alarm.index_5")],["weixin",a.global.t("Config.Alarm.index_6")],["tg","Telegram"]]);function de(e){const t=oe.value.find((t=>t.id===e));return t?`${t.data.title} (${se.get(t.sender_type)})`:""}const re={class:"p-20px"},ce={class:"alarm-info"},me={class:"alarm-title"},ue={key:1,class:"alarm-box"},ge={class:"alarm-info"},pe={class:"alarm-title"},_e=["innerHTML"],fe=l($({__name:"record-details",props:{row:{}},setup(e){const t=R(e,"row"),{t:n}=E(),a=T((()=>Object.entries(t.value.result.send_data).map((e=>{const t=de(e[0]);return{result:1===e[1],resultMsg:1===e[1]?n("Config.Alarm.index_108"):e[1],account:t}})))),i=W([{key:"account",title:n("Config.Alarm.index_106"),render:e=>e.account||"--"},{key:"resultMsg",title:n("Config.Alarm.index_107"),render:e=>U("span",{class:e.result?"text-primary":"text-error"},[e.resultMsg])}]);return(e,n)=>{const l=te;return H(),B("div",re,[S("div",ce,[S("div",me,I(e.$t("Config.Alarm.index_104")),1),O(a).length>0?(H(),D(l,{key:0,data:O(a),columns:O(i)},null,8,["data","columns"])):(H(),B("div",ue,I(O(t).result.stop_msg),1))]),S("div",ge,[S("div",pe,I(e.$t("Config.Alarm.index_105")),1),S("div",{class:"alarm-box",innerHTML:e.row.send_data.msg_list.join("<br />")},null,8,_e)])])}}}),[["__scopeId","data-v-23d9e8a8"]]),xe={class:"p-20px"},he=$({__name:"record",props:{row:{}},setup(e){const t=R(e,"row"),{t:n}=E(),a=()=>{C({title:n("Config.Alarm.index_95",[t.value.title]),content:n("Config.Alarm.index_96",[t.value.title]),onConfirm:async()=>{await A({task_id:t.value.id,record_ids:[]}),y()}})},{table:l,columns:c,setLoading:m}=f([{key:"create_time",title:n("Config.Alarm.index_97"),render:e=>o(e.create_time)},{key:"do_send",title:n("Config.Alarm.index_98"),render:e=>{let t=e.result.stop_msg;if(e.do_send){const a=Object.values(e.result.send_data).reduce(((e,t)=>(s(t)&&1===t?e.success++:d(t)&&e.fail++,e)),{success:0,fail:0});t=n("Config.Alarm.index_99",[a.success,a.fail])}return U(ne,null,{trigger:()=>U("span",{class:e.do_send?"text-primary":"text-error"},[e.do_send?n("Config.Alarm.index_110"):n("Config.Alarm.index_100")]),default:()=>U(V,null,[t])})}},{key:"details",title:n("Config.Alarm.index_101"),render:e=>U("a",{class:"bt-link",href:"javascript:;",onClick:()=>{u(e)}},[n("Config.Alarm.index_109")])},x({width:100,options:e=>[{label:n("Public.Btn.Del"),onClick:()=>{g(e)}}]})]),u=e=>{h({title:n("Config.Alarm.index_101"),width:480,data:{row:e},component:fe})},g=e=>{C({title:n("Config.Alarm.index_102"),content:n("Config.Alarm.index_103"),onConfirm:async()=>{await k({task_id:t.value.id,record_ids:[e.id]}),y()}})},w=F({task_id:t.value.id,page:1,size:10}),y=async()=>{try{m(!0);const{message:e}=await v(J(w));r(e)&&(l.data=i(e.list)?e.list:[],l.total=e.count)}finally{m(!1)}};return y(),(e,t)=>{const n=ae,i=_,o=ee,s=p;return H(),B("div",xe,[U(s,null,{toolsLeft:Q((()=>[U(n,{onClick:a},{default:Q((()=>[X(I(e.$t("Config.Alarm.index_94")),1)])),_:1})])),table:Q((()=>[U(i,{"max-height":382,loading:O(l).loading,data:O(l).data,columns:O(c)},null,8,["loading","data","columns"])])),pageRight:Q((()=>[U(o,{page:O(w).page,"onUpdate:page":t[0]||(t[0]=e=>O(w).page=e),"page-size":O(w).size,"onUpdate:pageSize":t[1]||(t[1]=e=>O(w).size=e),"item-count":O(l).total,onRefresh:y},null,8,["page","page-size","item-count"])])),_:1})])}}}),Ce=$({__name:"index",setup(e,{expose:n}){const a=Z((()=>c((()=>t.import("./form-legacy.js?v=1732601582185")),void 0))),{t:l}=E(),s=w("",{isEdit:!1,onRefresh:()=>{M()}}),d=()=>{s.data.isEdit=!1,s.title=l("Config.Alarm.index_1"),s.show=!0},{table:r,columns:m,setLoading:u}=f([{key:"title",title:l("Config.Alarm.index_7"),minWidth:140,ellipsis:{tooltip:!0}},y({minWidth:100,status:e=>({checkedValue:!0,checkedLabel:l("Config.Alarm.index_8"),uncheckedValue:!1,uncheckedLabel:l("Config.Alarm.index_9"),onClick:t=>{v(t,e)}})}),{key:"sender",title:l("Config.Alarm.index_92"),width:"14%",minWidth:140,ellipsis:{tooltip:!0},render:e=>{const{sender:t}=e,n=[];return t.forEach((e=>{const t=de(e);t&&n.push(t)})),n.join(l("Public.Punctuation.Comma"))}},{key:"view_msg",title:l("Config.Alarm.index_10"),width:"34%",minWidth:180,ellipsis:{tooltip:!0},render:e=>U("span",{innerHTML:e.view_msg},null)},{key:"last_check",title:l("Config.Alarm.index_11"),width:"14%",minWidth:140,render:e=>e.last_check?o(e.last_check):"--"},x({width:"12%",minWidth:150,options:e=>[{label:l("Config.Alarm.index_12"),onClick:()=>{k(e)}},{label:l("Public.Btn.Edit"),onClick:()=>{(e=>{s.data.row=e,s.data.isEdit=!0,s.title=l("Config.Alarm.index_2"),s.show=!0})(e)}},{label:l("Public.Btn.Del"),onClick:()=>{A(e)}}]})]),k=e=>{h({title:l("Config.Alarm.index_93",[e.title]),width:800,data:{row:e},component:he})},v=(e,t)=>{const n=l(e?"Config.Alarm.index_18":"Config.Alarm.index_13");C({title:l("Config.Alarm.index_14",[n,t.title]),content:l("Config.Alarm.index_15",[n.toLocaleLowerCase(),t.title]),onConfirm:async()=>{await j({task_id:t.id,status:e?1:0}),t.status=e}})},A=e=>{C({title:l("Config.Alarm.index_16"),content:l("Config.Alarm.index_17"),onConfirm:async()=>{await L({task_id:e.id}),M()}})},M=async(e=!1)=>{try{u(!0),e&&await async function(){const{message:e}=await b({refresh:0});oe.value=i(e)?e:[]}();const{message:t}=await z();r.data=i(t)?t:[]}finally{u(!1)}};return M(!0),Y((()=>{oe.value=[]})),n({init:M}),(e,t)=>{const n=ae,i=_,l=p,o=g;return H(),B("div",null,[U(l,null,{toolsLeft:Q((()=>[U(n,{type:"primary",onClick:d},{default:Q((()=>[X(I(e.$t("Config.Alarm.index_91")),1)])),_:1})])),table:Q((()=>[U(i,{loading:O(r).loading,data:O(r).data,columns:O(m)},null,8,["loading","data","columns"])])),_:1}),U(o,{show:O(s).show,"onUpdate:show":t[0]||(t[0]=e=>O(s).show=e),title:O(s).title,data:O(s).data,width:860,"min-height":340,footer:!0,component:O(a)},null,8,["show","title","data","component"])])}}}),we={class:"flex items-center"},ye={class:"flex-1 leading-[1.5]"},be={class:"flex"},ke=["href"],ve=l($({__name:"table-module",props:{row:{}},emits:["click"],setup(e,{emit:t}){const n=t,a=()=>{n("click")};return(e,t)=>(H(),B("div",we,[S("div",{class:q(["icon",e.row.name])},null,2),S("div",ye,[S("span",{class:"text-14px font-bold cursor-pointer",onClick:a},I(e.row.title),1),S("div",be,[S("span",null,I(e.row.ps),1),S("a",{class:"bt-link",href:e.row.help,target:"_blank"},">>"+I(e.$t("Config.Alarm.index_42")),9,ke)])])]))}}),[["__scopeId","data-v-70f7d608"]]),Ae=$({__name:"table-config",props:{row:{}},emits:["click"],setup(e,{emit:t}){const n=t,a=R(e,"row"),{t:i}=E(),l=T((()=>a.value.list.map((e=>e.data.title)).join(i("Public.Punctuation.Comma")))),o=()=>{n("click")};return(e,t)=>{const n=m;return H(),B("div",null,[O(a).list.length<=0?(H(),D(n,{key:0,type:"error",onClick:o},{default:Q((()=>[X(I(e.$t("Config.Alarm.index_40")),1)])),_:1})):(H(),B("span",{key:1,class:"cursor-pointer",onClick:o},I(e.$t("Config.Alarm.index_41",[O(l)])),1))])}}}),je=$({__name:"index",setup(e,{expose:t}){const{t:n}=E(),{table:a,columns:l,setLoading:o}=f([{key:"module",title:n("Config.Alarm.index_34"),width:"42%",minWidth:400,render:e=>U(ve,{row:e,onClick:()=>{s(e)}},null)},{key:"config",title:n("Config.Alarm.index_35"),minWidth:320,render:e=>U(Ae,{row:e,onClick:()=>{s(e)}},null)},x({width:100,options:e=>[{label:n("Public.Btn.Conf"),onClick:()=>{s(e)}}]})]),s=e=>{M({row:e,onRefresh:r})},d=[{name:"mail",title:n("Config.Alarm.index_3"),ps:n("Config.Alarm.index_36"),help:"https://www.bt.cn/bbs/thread-66183-1-1.html"},{name:"dingding",title:n("Config.Alarm.index_5"),ps:n("Config.Alarm.index_37"),help:"https://www.bt.cn/bbs/thread-108081-1-1.html"},{name:"weixin",title:n("Config.Alarm.index_6"),ps:n("Config.Alarm.index_38"),help:"https://www.bt.cn/bbs/thread-108116-1-1.html"},{name:"feishu",title:n("Config.Alarm.index_4"),ps:n("Config.Alarm.index_39"),help:"https://www.aapanel.com/forum/d/16942-aapanel-how-does-set-lark-or-feishu-notification"},{name:"tg",title:"Telegram",ps:"Use Telegram to send and receive panel notifications",help:"https://www.aapanel.com/forum/d/5115-how-to-add-telegram-to-panel-notifications"}],r=async()=>{try{o(!0);const{message:e}=await b({refresh:1});i(e)&&a.data.forEach((t=>{t.list=e.filter((e=>e.sender_type===t.name))}))}finally{o(!1)}};return a.data=d.map((e=>({...e,list:[]}))),G((()=>{r()})),t({init:r}),(e,t)=>{const n=_;return H(),B("div",null,[U(n,{loading:O(a).loading,data:O(a).data,columns:O(l)},null,8,["loading","data","columns"])])}}}),Le=$({__name:"index",setup(e,{expose:t}){const{t:n}=E(),{table:a,columns:l,setLoading:o}=f([{key:"log",title:n("Config.Alarm.index_7"),ellipsis:{tooltip:!0},render:e=>U("span",{innerHTML:e.log},null)},{key:"addtime",title:n("Config.Alarm.index_87"),width:150}]),s=F({p:1,limit:20}),d=async()=>{try{o(!0);const{message:e}=await P(J(s));r(e)&&(a.data=i(e.data)?e.data:[],a.total=u(e.page))}finally{o(!1)}};return K((()=>{d()})),t({init:d}),(e,t)=>{const n=_,i=ee,o=p;return H(),B("div",null,[U(o,null,{table:Q((()=>[U(n,{loading:O(a).loading,data:O(a).data,columns:O(l)},null,8,["loading","data","columns"])])),pageRight:Q((()=>[U(i,{page:O(s).p,"onUpdate:page":t[0]||(t[0]=e=>O(s).p=e),"page-size":O(s).limit,"onUpdate:pageSize":t[1]||(t[1]=e=>O(s).limit=e),"item-count":O(a).total,"store-key":"alarm-logs",onRefresh:d},null,8,["page","page-size","item-count"])])),_:1})])}}});e("default",$({__name:"index",setup(e){const{t:t}=E(),a=W("list"),i=[{key:"list",label:t("Config.Alarm.index_88"),component:Ce},{key:"settings",label:t("Config.Alarm.index_89"),component:je},{key:"logs",label:t("Config.Alarm.index_90"),component:Le}];return(e,t)=>{const l=n,o=ie;return H(),D(o,{class:"p-16px"},{default:Q((()=>[U(l,{value:O(a),"onUpdate:value":t[0]||(t[0]=e=>N(a)?a.value=e:null),options:i},null,8,["value"])])),_:1})}}}))}}}));