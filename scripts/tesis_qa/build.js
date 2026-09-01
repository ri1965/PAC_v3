const {Document,Packer,Paragraph,TextRun,HeadingLevel,AlignmentType,BorderStyle,Table,TableRow,TableCell,WidthType,ShadingType,PageBreak,Header,Footer,PageNumber,LevelFormat,convertMillimetersToTwip}=require('docx');
const fs=require('fs');

const AZ="1E3A5F", GR="6B7280", NA="0F2E4E", OR="B4611B";
const F="Aptos";

const P=(t,o={})=>new Paragraph({spacing:{after:o.after??120,line:o.line??276},alignment:o.al,indent:o.ind,
  border:o.border, shading:o.sh,
  children:[new TextRun({text:t,font:F,size:o.sz??22,bold:o.b,italics:o.i,color:o.c??"1E252D"})]});

const H1=t=>new Paragraph({heading:HeadingLevel.HEADING_1,spacing:{before:360,after:200},
  children:[new TextRun({text:t,font:F,size:32,bold:true,color:AZ})]});
const H2=t=>new Paragraph({heading:HeadingLevel.HEADING_2,spacing:{before:280,after:140},
  children:[new TextRun({text:t,font:F,size:26,bold:true,color:AZ})]});

// encabezado de diapo: "D07 · Título" + tiempo
const SL=(n,tit,min)=>new Paragraph({heading:HeadingLevel.HEADING_3,spacing:{before:300,after:100},
  border:{bottom:{style:BorderStyle.SINGLE,size:6,color:"D0D8E4"}},
  children:[
    new TextRun({text:`Diapo ${n}`,font:F,size:20,bold:true,color:GR}),
    new TextRun({text:"   ",font:F,size:20}),
    new TextRun({text:tit,font:F,size:24,bold:true,color:AZ}),
    new TextRun({text:`   ·   ${min}`,font:F,size:18,color:GR,italics:true})]});

const ROT=(et)=>new Paragraph({spacing:{before:140,after:60},
  children:[new TextRun({text:et,font:F,size:18,bold:true,color:OR,allCaps:true})]});

const SAY=t=>new Paragraph({spacing:{after:120,line:300},indent:{left:284},
  children:[new TextRun({text:t,font:F,size:22,color:"1E252D"})]});

const BUL=t=>new Paragraph({numbering:{reference:"vin",level:0},spacing:{after:60,line:276},
  children:[new TextRun({text:t,font:F,size:21,color:"1E252D"})]});

const NUM=t=>new Paragraph({spacing:{after:80,line:264},indent:{left:284},
  children:[new TextRun({text:t,font:F,size:19,color:GR,italics:true})]});

const QA=(q,r)=>[
  new Paragraph({spacing:{before:180,after:60},children:[new TextRun({text:q,font:F,size:21,bold:true,color:NA})]}),
  new Paragraph({spacing:{after:100,line:276},indent:{left:284},children:[new TextRun({text:r,font:F,size:21,color:"1E252D"})]})];

const doc=new Document({
  numbering:{config:[{reference:"vin",levels:[{level:0,format:LevelFormat.BULLET,text:"•",alignment:AlignmentType.LEFT,
    style:{paragraph:{indent:{left:568,hanging:284}}}}]}]},
  styles:{default:{document:{run:{font:F,size:22}}}},
  sections:[{
    properties:{page:{margin:{top:1134,bottom:1134,left:1300,right:1134}}},
    headers:{default:new Header({children:[new Paragraph({alignment:AlignmentType.RIGHT,
      border:{bottom:{style:BorderStyle.SINGLE,size:6,color:"D0D8E4"}},
      children:[new TextRun({text:"Guión de defensa oral · Proyecto PAC",font:F,size:16,color:GR,italics:true})]})]})},
    footers:{default:new Footer({children:[new Paragraph({alignment:AlignmentType.RIGHT,
      children:[new TextRun({text:"Roberto Inza · Universidad Austral · ",font:F,size:16,color:GR}),
                new TextRun({children:[PageNumber.CURRENT],font:F,size:16,color:GR})]})]})},
    children: BODY()
  }]
});
function BODY(){ return require('./contenido.js')({P,H1,H2,SL,ROT,SAY,BUL,NUM,QA,Paragraph,TextRun,AlignmentType,BorderStyle,F,AZ,GR,NA,OR}); }
Packer.toBuffer(doc).then(b=>{fs.writeFileSync('/tmp/guion/Guion_Defensa_PAC_v4.docx',b);console.log('ok');});
