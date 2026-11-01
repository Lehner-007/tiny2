import assert from 'node:assert/strict';
import { createTools } from '../../dist/mcp/tools.js';
import { parseFrame } from '../../dist/codec/frame.js';
const writes=[];
const transport={
 recvStatus:async()=>Buffer.from('2501000200000001010158020001013200000000017f2100000143000000553c00031000000000000000000000000000000000000000000000000000','hex'),
 xuRaw:async(selector,data)=>writes.push({selector,data}),
 sendVendor:async(data)=>writes.push({frame:parseFrame(data)}),nextSeq:()=>1,
};
const selections=[];
const manager={get:async(camera)=>{selections.push(camera);return transport;},takeReconnected:()=>false};
const tools=createTools(manager);
const call=(name,args)=>tools.find(t=>t.name===name).handler(args);
for(const [index,command] of ['wake','sleep','track','unlock','zoom-in','zoom-out','presets'].entries()) {
 for(const enabled of [true,false]) {
  const result=await call('obsbot_voice_control',{camera:'selected-camera',command,enabled});
  assert.equal(result.verified,false);
  const write=writes.at(-1);
  assert.equal(write.selector,6);
  assert.equal(write.data.length,60);
  assert.deepEqual([...write.data.subarray(0,4)],[0x15,2,index,Number(enabled)]);
 }
}
await call('obsbot_voice_language',{camera:'selected-camera',language:'english'});
assert.deepEqual([...writes.at(-1).data.subarray(0,4)],[0x15,2,101,1]);
for(const gesture of ['target','zoom','dynamic-zoom','mirror']) {
 const result=await call('obsbot_gesture_control',{camera:'selected-camera',gesture,enabled:false});
 assert.equal(result.verified,false);
 assert.equal(writes.at(-1).frame.payload[0],0);
}
const count=writes.length;
await assert.rejects(call('obsbot_voice_language',{language:'german'}));
await assert.rejects(call('obsbot_voice_control',{command:'wake',enabled:17}));
assert.equal(writes.length,count);
assert.ok(selections.every(x=>x==='selected-camera'));
transport.xuRaw=async()=>{throw new Error('USB failure');};
await assert.rejects(call('obsbot_voice_control',{command:'wake',enabled:true}),/USB failure/);
console.log('Voice/gesture transport, validation and error tests passed');
