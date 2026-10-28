const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
const element = () => ({textContent:'', value:'', hidden:false, style:{}, children:[], append(...items){this.children.push(...items)}, replaceChildren(){this.children=[]}, close(){}, scrollIntoView(){}, showModal(){}});
const storage = new Map();
const context = vm.createContext({console, Date, crypto:require('node:crypto').webcrypto,
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  $:id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id)},
  document:{createElement:element,querySelector:()=>element()},confirm:()=>true,
  results:[],index:0,lastBrief:'Night music',lastRecommendationBody:{journey_id:'first'},calibrationData:{},currentQuestions:[],orientationAnswers:[],calibrationAnswers:[{selected_label:'Nearby genres'}],calibrationSelection:{genre_distance:'2'},lastIntentTitle:'Night records',lastSummary:'Original explanation',lastCoverage:{},rabbitHoles:{},feedbackSubmitted:false,activeJobId:null,activeRequest:null,analysisReport:null,render(){},
});
const run = code=>vm.runInContext(code,context);
run(fs.readFileSync('listening_history.js','utf8'));
run(`results=[{entity:{title:'Original album'},reasons:[{claim:'Original reason',provenance:{source:'curator',confidence:1}}]}];saveJourney()`);
assert.equal(JSON.parse(storage.get('crateDiggerHistoryV1'))[0].results[0].reasons[0].provenance.confidence,1);
run('saveJourney()');assert.equal(run('readHistory().length'),1);
run("results.push({entity:{title:'Second album'},reasons:[{claim:'Second reason'}]});saveJourney();index=1;saveJourneyPosition();index=0;reopenJourney('first')");
assert.equal(context.index,1);assert.equal(context.results[1].entity.title,'Second album');
run('index=0;feedbackSubmitted=true;saveJourneyPosition();results=[];lastBrief="Changed";reopenJourney("first")');
assert.equal(context.lastBrief,'Night music');assert.equal(context.results[0].entity.title,'Original album');assert.equal(context.feedbackSubmitted,true);
run(`for(let n=0;n<55;n++){lastRecommendationBody={journey_id:String(n)};saveJourney()}`);
assert.equal(run('readHistory().length'),50);assert.equal(run('readHistory()[0].id'),'54');
run('savedJourneyId=null;index=1;saveJourneyPosition()');assert.equal(run('readHistory()[0].index'),0);
storage.set('crateDiggerHistoryV1','broken');assert.equal(run('readHistory().length'),0);
assert.match(elements.get('historyStatus').textContent,/could not be read/);
context.localStorage.setItem=()=>{throw Error('Quota exceeded')};run('saveJourney()');
assert.match(elements.get('historyStatus').textContent,/could not be saved/);assert.equal(context.results.length,2);
context.localStorage.setItem=(key,value)=>storage.set(key,value);
run('clearHistory()');assert.equal(storage.has('crateDiggerHistoryV1'),false);
console.log('Listening history: snapshot, reopen, deduplication, cap, deleted-entry protection, corruption, quota, clear passed');
