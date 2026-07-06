;(() => {
	const hrefs = ["../css/view-bind.css?v=1782899742524"]
	const stylesheetSelector = "link[rel=stylesheet]"
	const loaded = new Set(Array.from(document.querySelectorAll(stylesheetSelector)).map(link => link.href))
	const version = "1782899742524"
	const findLoadedLink = href => Array.from(document.querySelectorAll(stylesheetSelector)).find(link => link.href === href)
	const removeAfterLoad = (freshLink, staleLink) => {
		const remove = () => staleLink.remove()
		if (freshLink.sheet) {
			requestAnimationFrame(remove)
			return
		}
		freshLink.addEventListener("load", remove, { once: true })
	}
	for (const link of Array.from(document.querySelectorAll(stylesheetSelector))) {
		const url = new URL(link.href, location.href)
		if (url.origin !== location.origin || url.searchParams.get("v") === version) continue
		url.searchParams.set("v", version)
		if (loaded.has(url.href)) {
			const freshLink = findLoadedLink(url.href)
			if (freshLink && freshLink !== link) removeAfterLoad(freshLink, link)
			continue
		}
		const freshLink = document.createElement("link")
		freshLink.rel = "stylesheet"
		freshLink.href = url.href
		link.parentNode?.insertBefore(freshLink, link.nextSibling)
		loaded.add(url.href)
		removeAfterLoad(freshLink, link)
	}
	for (const href of hrefs) {
		const url = new URL(href, import.meta.url).href
		if (loaded.has(url)) continue
		const link = document.createElement("link")
		link.rel = "stylesheet"
		link.href = url
		document.head.appendChild(link)
		loaded.add(url)
	}
})();
import{r as e}from"./rolldown-runtime.js?v=1782899742524";import{Cn as t,Dn as n,En as r,Er as i,Ft as a,Sn as o,Sr as s,Zr as c,_r as l,bn as u,dn as ee,fn as te,kn as d,nn as f,qn as p,sr as m,xn as ne,yr as h}from"./vendor-utils.js?v=1782899742524";import{l as g}from"./vendor-vue.js?v=1782899742524";import{I as re,P as _,f as v,ht as ie,pt as ae,u as oe,xt as se,z as ce}from"./vendor-naive.js?v=1782899742524";import{$f as y,Bd as b,_c as x,cn as le,df as S,dp as C,jf as w,kf as T,n as E,pn as D,sf as O}from"./app.js?v=1782899742524";import{Hi as k}from"./app-components.js?v=1782899742524";f();var A={class:`font-600`},j={class:`info flex mt-50px w-820px mx-auto`},M={class:`tips py-40px w-50%`},N={class:`font-600 text-16px`},P={class:`mt-10px mb-20px font-600 text-16px`},F={key:0,class:`w-50% py-24px px-32px`},I={class:`my-16px`},L={class:`my-16px`},R={class:`w-100%`},z={class:`flex justify-end mt-8px`},ue={key:1,class:`w-50% p-30px`},B={class:`font-600 text-left`},V={class:`underline`},H={class:`text-16px my-20px text-left`},U={key:0,class:`ml-5px`},W=d({__name:`index`,setup(e){let{t:d}=g(),f=h(null),w=h(null),W=l({email:``,password:``,isPro:1}),G={email:{required:!0,trigger:[`blur`,`input`],message:d(`Component.BindAccount.index_4`)},password:{required:!0,trigger:[`blur`,`input`],message:d(`Component.BindAccount.index_5`)}},K=l({username:``,password:``,isPro:1}),de={username:{required:!0,trigger:[`blur`,`input`],message:d(`Component.BindAccount.index_4`)},password:{required:!0,trigger:[`blur`,`input`],message:d(`Component.BindAccount.index_5`)}},q=h(!1),J=h(!1),fe=e=>{J.value=e===`login`},Y=h(60),X=h(!0),Z,pe=()=>{X.value=!1,Z&&clearInterval(Z),Z=setInterval(()=>{Y.value--,Y.value<=0&&(clearInterval(Z),Y.value=60,X.value=!0)},1e3)},me=async()=>{await f.value?.validate();let{message:e}=await O(s(W));C(e)&&(e.status?(q.value=!0,T.success(e.msg)):T.error(e.msg))},he=()=>J.value?K:{username:W.email,password:W.password,isPro:1},Q=async()=>{await w.value?.validate();try{await b(s(he()))}catch(e){a(e,`message.validated`,!0)||(q.value=!0);return}await x({force:1}),E.push(`/`)},ge=()=>{pe(),S({email:J.value?K.username:W.email})},$=()=>{window.location.href=`${y()}/google/redirect`};return(e,a)=>{let s=le,l=ie,d=ce,h=se,g=_,y=k,b=v,x=D,S=oe,C=re,T=ae;return p(),ne(T,{class:`box pt-100px flex items-center text-center`},{default:m(()=>[u(`h1`,A,c(e.$t(`Login.index_26`)),1),u(`div`,j,[u(`div`,M,[a[7]||(a[7]=u(`h3`,{class:`font-600 mb-20px`},`aaPanel Pro`,-1)),u(`div`,N,c(e.$t(`Login.index_29`)),1),u(`div`,P,c(e.$t(`Login.index_30`)),1),n(s,{class:`text-left pl-30px w-400px`},{default:m(()=>[u(`li`,null,c(e.$t(`Login.index_27`)),1),u(`li`,null,c(e.$t(`Login.index_28`)),1)]),_:1})]),i(q)?(p(),t(`div`,ue,[u(`h3`,B,[r(c(e.$t(`Login.index_35`))+`: `,1),u(`span`,V,c(i(J)?i(K).username:i(W).email),1)]),u(`div`,H,[r(c(e.$t(`Login.index_36`))+`: `,1),a[15]||(a[15]=u(`span`,{class:`underline`},`support@aapanel.com`,-1))]),n(C,null,{default:m(()=>[n(l,{type:`primary`,size:`large`,onClick:a[6]||(a[6]=e=>Q())},{default:m(()=>[r(c(e.$t(`Login.index_37`)),1)]),_:1}),n(l,{size:`large`,onClick:ge,disabled:!i(X)},{default:m(()=>[r(c(e.$t(`Login.index_38`))+` `,1),i(X)?o(``,!0):(p(),t(`span`,U,`(`+c(i(Y))+`)`,1))]),_:1},8,[`disabled`])]),_:1})])):(p(),t(`div`,F,[n(S,{"default-value":`signup`,size:`large`,animated:``,"onUpdate:value":fe},{default:m(()=>[n(b,{name:`signup`,tab:`Sign up`,class:`text-left`},{default:m(()=>[n(y,{ref_key:`signFormRef`,ref:f,model:i(W),rules:G,size:`large`},{default:m(()=>[n(l,{class:`google-btn`,block:``,size:`large`,onClick:$},{icon:m(()=>[...a[8]||(a[8]=[u(`i`,{class:`i-common:google`},null,-1)])]),default:m(()=>[a[9]||(a[9]=u(`span`,null,`Continue with Google`,-1))]),_:1}),u(`div`,I,[n(d,null,{default:m(()=>[...a[10]||(a[10]=[r(`or`,-1)])]),_:1})]),n(g,{path:`email`},{default:m(()=>[n(h,{value:i(W).email,"onUpdate:value":a[0]||(a[0]=e=>i(W).email=e),placeholder:e.$t(`Config.Alarm.index_3`)},null,8,[`value`,`placeholder`])]),_:1}),n(g,{path:`password`},{default:m(()=>[n(h,{value:i(W).password,"onUpdate:value":a[1]||(a[1]=e=>i(W).password=e),type:`password`,placeholder:e.$t(`Config.Panel.index_66`)},null,8,[`value`,`placeholder`])]),_:1}),n(g,{"show-feedback":!1},{default:m(()=>[n(l,{type:`primary`,onClick:me,size:`large`,block:``},{default:m(()=>[r(c(e.$t(`Login.index_31`)),1)]),_:1})]),_:1})]),_:1},8,[`model`])]),_:1}),n(b,{name:`login`,tab:`Login`,class:`text-left`},{default:m(()=>[n(y,{ref_key:`loginFormRef`,ref:w,model:i(K),rules:de,size:`large`},{default:m(()=>[n(l,{class:`google-btn`,block:``,size:`large`,onClick:$},{icon:m(()=>[...a[11]||(a[11]=[u(`i`,{class:`i-common:google`},null,-1)])]),default:m(()=>[a[12]||(a[12]=u(`span`,null,`Continue with Google`,-1))]),_:1}),u(`div`,L,[n(d,null,{default:m(()=>[...a[13]||(a[13]=[r(`or`,-1)])]),_:1})]),n(g,{path:`username`},{default:m(()=>[n(h,{value:i(K).username,"onUpdate:value":a[2]||(a[2]=e=>i(K).username=e),placeholder:e.$t(`Config.Alarm.index_3`)},null,8,[`value`,`placeholder`])]),_:1}),n(g,{path:`password`},{default:m(()=>[n(h,{value:i(K).password,"onUpdate:value":a[3]||(a[3]=e=>i(K).password=e),type:`password`,placeholder:e.$t(`Config.Panel.index_66`),onKeyup:a[4]||(a[4]=ee(te(e=>Q(),[`prevent`]),[`enter`]))},null,8,[`value`,`placeholder`])]),_:1})]),_:1},8,[`model`]),u(`div`,R,[n(l,{type:`primary`,onClick:a[5]||(a[5]=e=>Q()),size:`large`,block:``},{default:m(()=>[r(c(e.$t(`Login.index_32`)),1)]),_:1}),u(`div`,z,[n(x,{target:`_blank`,href:`https://www.aapanel.com/user_admin/login?page=reset`},{default:m(()=>[...a[14]||(a[14]=[r(`Forget Password>>`,-1)])]),_:1})])])]),_:1})]),_:1})]))])]),_:1})}}}),G=e({default:()=>K}),K=w(W,[[`__scopeId`,`data-v-caffe03c`]]);export{G as t};