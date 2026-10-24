import path from 'node:path';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../..');
const deps=process.env.REMOTION_DEPS_DIR||path.resolve(here,'../../../orb-demo-video/node_modules');
const req=createRequire(path.join(deps,'remotion/package.json'));
const {bundle}=req('@remotion/bundler');
const {openBrowser,selectComposition,renderStill,renderMedia}=req('@remotion/renderer');
const browserExecutable=path.join(deps,'.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
const binariesDirectory=path.join(deps,'@remotion/compositor-win32-x64-msvc');
if(!fs.existsSync(browserExecutable))throw new Error('Existing Remotion Chromium not found. No browser will be downloaded. Set REMOTION_DEPS_DIR to the existing runtime.');
const out=path.join(root,'output/orb-product-demo');
fs.mkdirSync(path.join(out,'review'),{recursive:true});
const bundleDir=path.join(out,'bundle');
const hash=crypto.createHash('sha256');
for(const name of ['Root.jsx','motion.css','timeline.json',...fs.readdirSync(path.join(here,'public')).sort().map(n=>'public/'+n)])hash.update(fs.readFileSync(path.join(here,name)));
const fingerprint=hash.digest('hex');const stamp=path.join(out,'bundle-fingerprint.txt');
const reuse=process.argv.includes('--reuse');
if(reuse&&(!fs.existsSync(stamp)||fs.readFileSync(stamp,'utf8')!==fingerprint))throw new Error('Bundle is stale; render a fresh review first.');
console.log(reuse?'Using verified review bundle':'Bundling current composition');
const serveUrl=reuse?bundleDir:await bundle({entryPoint:path.join(here,'Root.jsx'),publicDir:path.join(here,'public'),outDir:path.join(out,'bundle'),
 gitSource:null,onProgress:(p)=>{if(p===1)console.log('Remotion bundle ready');},
 webpackOverride:(config)=>({...config,resolve:{...config.resolve,modules:[deps,...(config.resolve?.modules||['node_modules'])]}})});
if(!reuse)fs.writeFileSync(stamp,fingerprint);
console.log('Starting existing Chromium renderer');
const browser=await openBrowser('chrome',{browserExecutable,logLevel:'error'});
const mode=process.argv[2]||'review';
const patch=mode.startsWith('patch-');
const orientation=patch?mode.slice('patch-'.length):mode;
const log=[];
const common={serveUrl,puppeteerInstance:browser,browserExecutable,inputProps:{},logLevel:'error',
 onBrowserLog:(event)=>{if(event.type==='error')console.error('Browser:',event.text);if(event.text?.includes('layout_qa'))log.push(event.text);}};
const reviewSeconds=[0,5.9,9.5,13.5,19,23,28,37,42,48,56,59,62,68,75,80,83,85,94];
try{
 for(const [id,suffix] of [['Orb-Landscape','landscape'],['Orb-Portrait','portrait']]){
   if(orientation==='landscape'&&suffix!=='landscape'||orientation==='portrait'&&suffix!=='portrait')continue;
  const composition=await selectComposition({...common,id});
  if(mode==='review'||mode==='covers'){
   for(const second of mode==='covers'?[0]:reviewSeconds){
    const frame=Math.round(second*30);const output=path.join(out,'review',`${suffix}-${String(frame).padStart(4,'0')}.png`);
    await renderStill({...common,composition,frame,output,imageFormat:'png'});
    if(frame===0)fs.copyFileSync(output,path.join(out,`Orb-Cover-${suffix}.png`));
    console.log(`Review ${suffix} ${second}s`);
   }
   }else{
    const filename=patch?`work/Orb-Architecture-${suffix}.mp4`:suffix==='landscape'?'Orb-Product-Demo-1920x1080.mp4':'Orb-Product-Demo-1080x1920.mp4';
   let last=-1;
   await renderMedia({...common,composition,outputLocation:path.join(out,filename),codec:'h264',crf:16,
     imageFormat:'jpeg',jpegQuality:95,pixelFormat:'yuv420p',audioCodec:'aac',audioBitrate:'320k',
      x264Preset:'medium',concurrency:2,binariesDirectory,enforceAudioTrack:!patch,
      ...(patch?{frameRange:[66*30,72*30-1],muted:true}:{}),
      metadata:{title:'Orb — Perceive. Remediate. Decode.',comment:'Orb AI; English synthetic narration; original score; authentic AWS sample; recreated UI interactions; provenance in companion notes.'},
     onProgress:({progress})=>{const pct=Math.floor(progress*100);if(pct>=last+5){last=pct;console.log(`Render ${suffix}: ${pct}%`);}}});
   console.log(`Exported ${filename}`);
  }
 }
 fs.writeFileSync(path.join(out,'review','layout-log.json'),JSON.stringify(log,null,2));
}finally{await browser.close({silent:true});}
