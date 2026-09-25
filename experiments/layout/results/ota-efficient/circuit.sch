v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {CHIPJEV / ota5_p} 40 -180 0 0 0.52 0.52 {layer=3}
T {01  DIFFERENTIAL INPUT + ACTIVE LOAD} 220 -100 0 0 0.32 0.32 {layer=6}
T {SINGLE-STAGE OTA} 650 -100 0 0 0.32 0.32 {layer=6}
T {SKY130 / 5 MOSFETs / W/L in um / live candidate} 40 1320 0 0 0.28 0.28 {layer=14}
N 40 100 1120 100 {}
N 40 100 40 470 {}
N 40 900 1120 900 {}
N 40 530 40 900 {}
N 580 170 580 100 {}
N 540 200 500 200 {}
N 580 260 580 230 {}
N 480 370 480 260 {}
N 480 260 720 260 {}
N 720 260 720 370 {}
N 640 400 680 400 {}
N 400 400 440 400 {}
N 720 900 720 790 {}
N 480 900 480 790 {}
N 720 730 720 430 {}
N 720 660 640 660 {}
N 640 660 640 760 {}
N 640 760 680 760 {}
N 480 730 480 430 {}
N 640 660 400 660 {}
N 400 660 400 760 {}
N 400 760 440 760 {}
N 480 500 1100 500 {}
N 500 200 500 1010 {}
N 500 1070 500 1260 {}
N 40 900 40 1260 {}
N 40 1260 1120 1260 {}
C {devices/vsource.sym} 40 500 0 0 {name=VDD value=1.8 m=1 hide_texts=true}
T {VDD} 75 476 0 0 0.25 0.25 {layer=3}
T {1.8} 75 503 0 0 0.21 0.21 {layer=14}
C {devices/lab_wire.sym} 40 100 0 0 {name=net3 lab=vdd}
C {devices/lab_wire.sym} 40 900 0 0 {name=net4 lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 560 200 0 0 {name=M1 L=1.69667 W=112.15 nf=3 mult=1 ad=21.6823 as=21.6823 pd=150.693 ps=150.693 nrd=0.00258583 nrs=0.00258583 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 580 200 0 0 {name=net6 lab=vdd hide_texts=true}
T {M1} 605 182 0 0 0.29 0.29 {layer=3}
T {112/1.7} 605 207 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 540 200 0 0 {name=net9 lab=s1t}
C {sky130_fd_pr/pfet_01v8.sym} 700 400 0 0 {name=M2 L=1.69667 W=848.333 nf=17 mult=1 ad=130.244 as=130.244 pd=903.455 ps=903.455 nrd=0.000341847 nrs=0.000341847 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 720 400 0 0 {name=net11 lab=vdd hide_texts=true}
T {M2} 745 382 0 0 0.29 0.29 {layer=3}
T {848/1.7} 745 407 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/pfet_01v8.sym} 460 400 0 0 {name=M3 L=1.69667 W=848.333 nf=17 mult=1 ad=130.244 as=130.244 pd=903.455 ps=903.455 nrd=0.000341847 nrs=0.000341847 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 480 400 0 0 {name=net15 lab=vdd hide_texts=true}
T {M3} 505 382 0 0 0.29 0.29 {layer=3}
T {848/1.7} 505 407 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 580 260 0 0 {name=net18 lab=t1}
C {devices/lab_wire.sym} 640 400 0 0 {name=net19 lab=inp}
C {devices/lab_wire.sym} 400 400 0 0 {name=net20 lab=inn}
C {sky130_fd_pr/nfet_01v8.sym} 700 760 0 0 {name=M4 L=1.69667 W=26.468 nf=1 mult=1 ad=7.67572 as=7.67572 pd=53.516 ps=53.516 nrd=0.0109566 nrs=0.0109566 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 720 760 0 0 {name=net22 lab=0 hide_texts=true}
T {M4} 745 742 0 0 0.29 0.29 {layer=3}
T {26.5/1.7} 745 767 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/nfet_01v8.sym} 460 760 0 0 {name=M5 L=1.69667 W=26.468 nf=1 mult=1 ad=7.67572 as=7.67572 pd=53.516 ps=53.516 nrd=0.0109566 nrs=0.0109566 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 480 760 0 0 {name=net26 lab=0 hide_texts=true}
T {M5} 505 742 0 0 0.29 0.29 {layer=3}
T {26.5/1.7} 505 767 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 720 730 0 0 {name=net29 lab=x1}
C {devices/lab_wire.sym} 480 730 0 0 {name=net30 lab=out}
C {devices/vsource.sym} 500 1040 0 0 {name=V_S1T value=0.6975 m=1 hide_texts=true}
T {V_S1T} 535 1016 0 0 0.25 0.25 {layer=3}
T {0.6975} 535 1043 0 0 0.21 0.21 {layer=14}
