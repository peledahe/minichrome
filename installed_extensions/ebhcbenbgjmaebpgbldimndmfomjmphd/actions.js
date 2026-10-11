import{f as u}from"./globals.js";import{q as l,h as n,s as f,aU as y,aM as s,p as r,b7 as h,b8 as b,b9 as g,ba as p,bb as m}from"./onboarding.js";/**
 * @license lucide-react v0.300.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const K=u("Cloud",[["path",{d:"M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z",key:"p7xjir"}]]);/**
 * @license lucide-react v0.300.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const x=u("KeyRound",[["path",{d:"M2 18v3c0 .6.4 1 1 1h4v-3h3v-3h2l1.4-1.4a6.5 6.5 0 1 0-4-4Z",key:"167ctg"}],["circle",{cx:"16.5",cy:"7.5",r:".5",key:"1kog09"}]]);/**
 * @license lucide-react v0.300.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const E=u("X",[["path",{d:"M18 6 6 18",key:"1bl5f8"}],["path",{d:"m6 6 12 12",key:"d8bk6v"}]]);function M(a,e){if(!(a instanceof l))return e("billing.error.generic");switch(a.code){case"network":return e("billing.error.network");case"invalid_key":return e("billing.error.invalidKey");case"license_inactive":return e("billing.error.inactive");case"device_limit":return e("billing.error.deviceLimit");case"payments_unavailable":return e("billing.error.payments");case"rate_limited":return e("billing.error.rateLimited");default:return e("billing.error.generic")}}async function B(a,e,t={}){var w;const i=await n(),k=t.shown?{shown:{amount:t.shown.amount,currency:t.shown.currency.toLowerCase(),approx:t.shown.approx}}:{},d=()=>r("/v1/checkout",{iid:i.id,plan:a,trigger:e,...k},15e3);let c;try{c=await d()}catch(o){if(o instanceof l&&(o.code==="unknown_install"||o.code==="plan_unavailable"))await f({force:!0}),c=await d();else throw o}await chrome.storage.local.set({[y.pendingCheckout]:{id:c.checkout_id,at:Date.now(),plan:a}}),await s("checkout_open",{plan:a,trigger:e}),await((w=t.beforeOpen)==null?void 0:w.call(t)),await chrome.tabs.create({url:c.url})}async function v(a){const e=navigator.locks;return!e||typeof e.request!="function"?a():e.request(b,()=>a())}async function _(a,e){const t=await g(e,a),i=t?p(t):null;if(!i)throw new l("internal",200);return await m({entitlement:e}),await chrome.storage.local.remove(y.pendingCheckout),i}async function I(a){const e=await n();try{const t=await v(async()=>{const{entitlement:i}=await r("/v1/license/activate",{iid:e.id,key:a.trim(),method:"key"});return _(e.id,i)});return await h(a.trim()),await s("license_activate",{method:"key",ok:!0}),t}catch(t){throw await s("license_activate",{method:"key",ok:!1,error:t instanceof l?t.code:"internal"}),t}}async function S(a){const e=await n();await r("/v1/license/recover",{iid:e.id,email:a.trim()}),await s("license_recover")}async function q(){const a=await n();await v(async()=>{await r("/v1/license/deactivate",{iid:a.id}),await m({entitlement:null})}),await h(null)}async function N(){const a=await n(),{url:e}=await r("/v1/portal",{iid:a.id});await chrome.tabs.create({url:e})}export{K as C,x as K,E as X,I as a,M as b,q as d,N as o,S as r,B as s};
