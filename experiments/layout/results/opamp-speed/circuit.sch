v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {CHIPJEV / ota5_n+inv_cas} 40 -180 0 0 0.52 0.52 {layer=3}
T {01  DIFFERENTIAL INPUT + ACTIVE LOAD} 220 -100 0 0 0.32 0.32 {layer=6}
T {02  GAIN + COMPENSATION} 1230 -100 0 0 0.32 0.32 {layer=6}
T {SKY130 / 9 MOSFETs / W/L in um / live candidate} 40 1320 0 0 0.28 0.28 {layer=14}
N 40 100 1940 100 {}
N 40 100 40 470 {}
N 40 900 1940 900 {}
N 40 530 40 900 {}
N 580 830 580 900 {}
N 540 800 500 800 {}
N 580 740 580 770 {}
N 480 630 480 740 {}
N 480 740 720 740 {}
N 720 740 720 630 {}
N 640 600 680 600 {}
N 400 600 440 600 {}
N 720 100 720 210 {}
N 480 100 480 210 {}
N 720 270 720 570 {}
N 720 340 640 340 {}
N 640 340 640 240 {}
N 640 240 680 240 {}
N 480 270 480 570 {}
N 640 340 400 340 {}
N 400 340 400 240 {}
N 400 240 440 240 {}
N 480 500 1100 500 {}
N 1460 830 1460 900 {}
N 1100 500 1200 500 {}
N 1200 500 1200 800 {}
N 1200 800 1420 800 {}
N 1460 100 1460 170 {}
N 1460 650 1460 770 {}
N 1460 230 1460 350 {}
N 1460 410 1460 590 {}
N 1200 500 1200 200 {}
N 1200 200 1420 200 {}
N 1500 620 1680 620 {}
N 1500 380 1780 380 {}
N 1460 500 1880 500 {}
N 500 800 500 1010 {}
N 500 1070 500 1260 {}
N 1680 620 1680 1010 {}
N 1680 1070 1680 1260 {}
N 1780 380 1780 1110 {}
N 1780 1170 1780 1260 {}
N 40 900 40 1260 {}
N 40 1260 1940 1260 {}
C {devices/vsource.sym} 40 500 0 0 {name=VDD value=1.8 m=1 hide_texts=true}
T {VDD} 75 476 0 0 0.25 0.25 {layer=3}
T {1.8} 75 503 0 0 0.21 0.21 {layer=14}
C {devices/lab_wire.sym} 40 100 0 0 {name=net3 lab=vdd}
C {devices/lab_wire.sym} 40 900 0 0 {name=net4 lab=0}
C {sky130_fd_pr/nfet_01v8.sym} 560 800 0 0 {name=M1 L=0.15 W=6.42 nf=1 mult=1 ad=1.8618 as=1.8618 pd=13.42 ps=13.42 nrd=0.0451713 nrs=0.0451713 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 580 800 0 0 {name=net6 lab=0 hide_texts=true}
T {M1} 605 782 0 0 0.29 0.29 {layer=3}
T {6.42/0.15} 605 807 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 540 800 0 0 {name=net9 lab=s1t}
C {sky130_fd_pr/nfet_01v8.sym} 700 600 0 0 {name=M2 L=0.15 W=56.1 nf=2 mult=1 ad=8.1345 as=16.269 pd=56.68 ps=113.36 nrd=0.00516934 nrs=0.00516934 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 720 600 0 0 {name=net11 lab=0 hide_texts=true}
T {M2} 745 582 0 0 0.29 0.29 {layer=3}
T {56.1/0.15} 745 607 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/nfet_01v8.sym} 460 600 0 0 {name=M3 L=0.15 W=56.1 nf=2 mult=1 ad=8.1345 as=16.269 pd=56.68 ps=113.36 nrd=0.00516934 nrs=0.00516934 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 480 600 0 0 {name=net15 lab=0 hide_texts=true}
T {M3} 505 582 0 0 0.29 0.29 {layer=3}
T {56.1/0.15} 505 607 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 580 740 0 0 {name=net18 lab=t1}
C {devices/lab_wire.sym} 640 600 0 0 {name=net19 lab=inp}
C {devices/lab_wire.sym} 400 600 0 0 {name=net20 lab=inn}
C {sky130_fd_pr/pfet_01v8.sym} 700 240 0 0 {name=M4 L=0.15 W=4.17 nf=1 mult=1 ad=1.2093 as=1.2093 pd=8.92 ps=8.92 nrd=0.0695444 nrs=0.0695444 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 720 240 0 0 {name=net22 lab=vdd hide_texts=true}
T {M4} 745 222 0 0 0.29 0.29 {layer=3}
T {4.17/0.15} 745 247 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/pfet_01v8.sym} 460 240 0 0 {name=M5 L=0.15 W=4.17 nf=1 mult=1 ad=1.2093 as=1.2093 pd=8.92 ps=8.92 nrd=0.0695444 nrs=0.0695444 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 480 240 0 0 {name=net26 lab=vdd hide_texts=true}
T {M5} 505 222 0 0 0.29 0.29 {layer=3}
T {4.17/0.15} 505 247 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 720 270 0 0 {name=net29 lab=x1}
C {devices/lab_wire.sym} 480 270 0 0 {name=net30 lab=o1}
C {sky130_fd_pr/nfet_01v8.sym} 1440 800 0 0 {name=M6 L=0.178333 W=0.42 nf=1 mult=1 ad=0.1218 as=0.1218 pd=1.42 ps=1.42 nrd=0.690476 nrs=0.690476 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 1460 800 0 0 {name=net32 lab=0 hide_texts=true}
T {M6} 1485 782 0 0 0.29 0.29 {layer=3}
T {0.42/0.178} 1485 807 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/nfet_01v8.sym} 1480 620 0 1 {name=M7 L=0.178333 W=89.1667 nf=2 mult=1 ad=12.9292 as=25.8583 pd=89.7467 ps=179.493 nrd=0.00325234 nrs=0.00325234 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 1460 620 0 0 {name=net36 lab=0 hide_texts=true}
T {M7} 1365 602 0 0 0.29 0.29 {layer=3}
T {89.2/0.178} 1365 627 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/pfet_01v8.sym} 1480 380 0 1 {name=M8 L=0.178333 W=1.16808 nf=1 mult=1 ad=0.338744 as=0.338744 pd=2.91617 ps=2.91617 nrd=0.24827 nrs=0.24827 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 1460 380 0 0 {name=net40 lab=vdd hide_texts=true}
T {M8} 1365 362 0 0 0.29 0.29 {layer=3}
T {1.17/0.178} 1365 387 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/pfet_01v8.sym} 1440 200 0 0 {name=M9 L=0.178333 W=32.4567 nf=1 mult=1 ad=9.41243 as=9.41243 pd=65.4933 ps=65.4933 nrd=0.00893499 nrs=0.00893499 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 1460 200 0 0 {name=net44 lab=vdd hide_texts=true}
T {M9} 1485 182 0 0 0.29 0.29 {layer=3}
T {32.5/0.178} 1485 207 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 1460 650 0 0 {name=net47 lab=s2a}
C {devices/lab_wire.sym} 1460 230 0 0 {name=net48 lab=s2c}
C {devices/lab_wire.sym} 1460 410 0 0 {name=net49 lab=out}
C {devices/lab_wire.sym} 1500 620 0 0 {name=net50 lab=s2cn}
C {devices/lab_wire.sym} 1500 380 0 0 {name=net51 lab=s2cp}
C {devices/vsource.sym} 500 1040 0 0 {name=V_S1T value=0.735 m=1 hide_texts=true}
T {V_S1T} 535 1016 0 0 0.25 0.25 {layer=3}
T {0.735} 535 1043 0 0 0.21 0.21 {layer=14}
C {devices/vsource.sym} 1680 1040 0 0 {name=V_S2CN value=1.015 m=1 hide_texts=true}
T {V_S2CN} 1715 1016 0 0 0.25 0.25 {layer=3}
T {1.015} 1715 1043 0 0 0.21 0.21 {layer=14}
C {devices/vsource.sym} 1780 1140 0 0 {name=V_S2CP value=0.2775 m=1 hide_texts=true}
T {V_S2CP} 1815 1116 0 0 0.25 0.25 {layer=3}
T {0.2775} 1815 1143 0 0 0.21 0.21 {layer=14}
