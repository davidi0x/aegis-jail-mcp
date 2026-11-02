const {chromium}=require('playwright');
(async()=>{const b=await chromium.launch();
for(const [k,o,w,h] of [['banner','banner.png',1280,400],['social','social-preview.png',1280,640],['how','how-it-works.png',1280,0]]){
 const p=await b.newPage({viewport:{width:1280,height:h||800},deviceScaleFactor:2});
 await p.goto('file://'+__dirname+'/assets.html?k='+k);await p.waitForTimeout(600);
 await p.locator('#cap').screenshot({path:__dirname+'/../../../docs/images/'+o});}
await b.close()})();
