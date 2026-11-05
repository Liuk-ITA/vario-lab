/* Independent audio renderer: pitch and beep phases never restart on parameter updates. */
'use strict';
class VarioTone extends AudioWorkletProcessor {
  constructor(){
    super();this.settings={enabled:false,mode:'silent',hz:550,period:.5,duty:.45,volume:0};
    this.carrier=0;this.beat=0;this.frequency=550;this.envelope=0;this.age=1;
    this.port.onmessage=({data:d})=>{
      const enabled=!!d.enabled;
      if(enabled&&(!this.settings.enabled||d.mode!==this.settings.mode))this.beat=0;
      if(!enabled){this.settings.enabled=false;return;}
      if(![d.hz,d.period,d.duty,d.volume].every(Number.isFinite)||d.hz<20||d.hz>5000||d.period<=0||d.duty<=0||d.duty>1)return;
      if(d.splitTone&&(!Number.isFinite(d.secondHz)||d.secondHz<20||d.secondHz>5000||!Number.isFinite(d.splitFraction)||d.splitFraction<=0||d.splitFraction>=1))return;
      if(d.secondHz&&!d.splitTone&&(![d.secondHz,d.toneLength,d.gap].every(Number.isFinite)||d.secondHz<20||d.secondHz>5000||d.toneLength<=0||d.gap<0))return;
      this.settings={...d,enabled:true,volume:Math.max(0,Math.min(.4,d.volume))};this.age=0;
    };
  }
  process(inputs,outputs){
    const output=outputs[0];if(!output?.length)return true;
    const pitch=1-Math.exp(-1/(sampleRate*(this.settings.splitTone?.002:.025))),attack=1-Math.exp(-1/(sampleRate*.004)),release=1-Math.exp(-1/(sampleRate*.008));
    for(let i=0;i<output[0].length;i++){
      const s=this.settings;this.age+=1/sampleRate;
      const active=s.enabled&&this.age<.3;
      if(active)this.beat=(this.beat+1/(s.period*sampleRate))%1;
      const pos=this.beat*s.period;
      let on=s.duty===1||this.beat<s.duty,hz=s.hz;
      if(s.splitTone){hz=this.beat<s.duty*s.splitFraction?s.hz:s.secondHz;}
      else if(s.secondHz){
        on=pos<s.toneLength||(pos>=s.toneLength+s.gap&&pos<2*s.toneLength+s.gap);
        if(pos>=s.toneLength+s.gap)hz=s.secondHz;
      }
      if(active)this.frequency+=pitch*(hz-this.frequency);
      const target=active&&on?s.volume:0;
      this.envelope+=(target>this.envelope?attack:release)*(target-this.envelope);
      this.carrier=(this.carrier+this.frequency/sampleRate)%1;
      const value=Math.sin(this.carrier*2*Math.PI)*this.envelope;
      for(const channel of output)channel[i]=value;
    }
    return true;
  }
}
registerProcessor('vario-tone',VarioTone);
