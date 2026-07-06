;(() => {
	const hrefs = ["../css/feature-Charts.css?v=1782899742524"]
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
import{r as e}from"./rolldown-runtime.js?v=1782899742524";import{Cn as t,Er as n,Jr as r,Rn as i,Vn as a,Wn as o,ar as s,f as c,kn as l,n as u,nn as d,qn as f,y as p,yr as m}from"./vendor-utils.js?v=1782899742524";import{nn as h}from"./vendor-naive.js?v=1782899742524";import{jf as g}from"./app.js?v=1782899742524";import{D as _,E as v,O as y,T as b,a as x,b as S,c as C,d as w,f as T,g as E,i as D,j as O,l as k,m as A,o as j,p as M,r as N,s as P,u as F,w as I}from"./vendor-charts.js?v=1782899742524";d(),O([T,E,C,A,x,j,k,b,y,D,N]);var L=_,R=l({__name:`index`,props:{width:{type:[Number,String],default:`100%`},height:{type:[Number,String],default:`200px`},dataZoom:{type:Boolean,default:!1},option:{type:Object,required:!0}},setup(e,{expose:c}){let l=e,u=m(null),d=null;function g(){u.value!==null&&(d=L.getInstanceByDom(u.value),d??(d=L.init(u.value)),d.setOption(l.option,!0))}function _(){u.value!==null&&L.getInstanceByDom(u.value)?.resize()}s(()=>l.option,e=>{e&&i(()=>{g()})},{immediate:!0,deep:!0});let v=p(_,300,{maxWait:800});return o(()=>{g(),window.addEventListener(`resize`,v)}),a(()=>{u.value&&(L.getInstanceByDom(u.value)?.dispose(),window.removeEventListener(`resize`,v))}),c({getChart:()=>d}),(i,a)=>(f(),t(`div`,{ref_key:`chartRef`,ref:u,style:r({width:n(h)(e.width),height:n(h)(e.height)})},null,4))}}),z=e({default:()=>B}),B=R;O([T,E,C,A,x,j,k,M,v,y,D,N]);var V=_;d();var H=l({__name:`index`,props:{width:{type:[Number,String],default:`100%`},height:{type:[Number,String],default:`200px`},dataZoom:{type:Boolean,default:!1},option:{type:Object,required:!0}},setup(e,{expose:l}){let u=e,d=m(null);function g(){if(d.value===null)return;let e=V.getInstanceByDom(d.value);e??(e=V.init(d.value)),e.setOption(u.option,!0),requestAnimationFrame(()=>e.resize())}function _(){d.value!==null&&V.getInstanceByDom(d.value)?.resize()}s(()=>u.option,e=>{e&&i(()=>{g()})},{immediate:!0,deep:!0});let v=p(_,80,{maxWait:240});return c(d,()=>{v()}),o(()=>{i(()=>{g(),window.addEventListener(`resize`,v)})}),a(()=>{d.value&&(V.getInstanceByDom(d.value)?.dispose(),window.removeEventListener(`resize`,v))}),l({resize:_,getChart:()=>V.getInstanceByDom(d.value)}),(i,a)=>(f(),t(`div`,{ref_key:`chartRef`,ref:d,class:`bt-line-chart`,style:r({width:n(h)(e.width),height:n(h)(e.height)})},null,4))}}),U=e({default:()=>W}),W=g(H,[[`__scopeId`,`data-v-ba6e3b19`]]);O([w,T,E,C,A,x,j,k,P,S,y,D,N,F]);var G=_;d();var K=l({__name:`index`,props:{width:{type:[Number,String],default:`100%`},height:{type:[Number,String],default:`200px`},dataZoom:{type:Boolean,default:!1},option:{type:Object,required:!0}},setup(e,{expose:c}){let l=e,d=m(null),g=!0;async function _(){if(g){let{data:e}=await u.get(`/static/vite/data/world.json`);G.registerMap(`world`,e),g=!1}if(d.value===null)return;let e=G.getInstanceByDom(d.value);e??(e=G.init(d.value)),e.setOption(l.option,!0)}function v(){d.value!==null&&G.getInstanceByDom(d.value)?.resize()}s(()=>l.option,e=>{e&&i(()=>{_()})},{immediate:!0,deep:!0});let y=p(v,300,{maxWait:800});return o(async()=>{window.addEventListener(`resize`,y)}),a(()=>{d.value&&(G.getInstanceByDom(d.value)?.dispose(),window.removeEventListener(`resize`,y))}),c({resize:v}),(i,a)=>(f(),t(`div`,{ref_key:`chartRef`,ref:d,style:r({width:n(h)(e.width),height:n(h)(e.height)})},null,4))}}),q=e({default:()=>J}),J=K;O([w,T,E,C,A,x,j,k,I,y,D,N]);var Y=_;d();var X=l({__name:`index`,props:{width:{type:[Number,String],default:`100%`},height:{type:[Number,String],default:`200px`},dataZoom:{type:Boolean,default:!1},option:{type:Object,required:!0}},setup(e){let c=e,l=m(null);function u(){if(l.value===null)return;let e=Y.getInstanceByDom(l.value);e??(e=Y.init(l.value)),e.setOption(c.option,!0)}function d(){l.value!==null&&Y.getInstanceByDom(l.value)?.resize()}s(()=>c.option,e=>{e&&i(()=>{u()})},{immediate:!0,deep:!0});let g=p(d,300,{maxWait:800});return o(()=>{i(()=>{u(),window.addEventListener(`resize`,g)})}),a(()=>{l.value&&(Y.getInstanceByDom(l.value)?.dispose(),window.removeEventListener(`resize`,g))}),(i,a)=>(f(),t(`div`,{ref_key:`chartRef`,ref:l,style:r({width:n(h)(e.width),height:n(h)(e.height)})},null,4))}}),Z=e({default:()=>Q}),Q=X;export{z as a,U as i,q as n,G as r,Z as t};