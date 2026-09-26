v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {CHIPJEV / cmota_p+inv_cas} 40 -180 0 0 0.52 0.52 {layer=3}
T {01  DIFFERENTIAL INPUT + ACTIVE LOAD} 220 -100 0 0 0.32 0.32 {layer=6}
T {02  GAIN + COMPENSATION} 1230 -100 0 0 0.32 0.32 {layer=6}
T {SKY130 / 13 MOSFETs / W/L in um / live candidate} 40 1320 0 0 0.28 0.28 {layer=14}
N 40 100 1940 100 {}
N 40 100 40 470 {}
N 40 900 1940 900 {}
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
N 480 620 400 620 {}
N 400 620 400 760 {}
N 400 760 440 760 {}
N 220 900 220 790 {}
N 980 900 980 790 {}
N 260 760 400 760 {}
N 720 660 900 660 {}
N 900 660 900 760 {}
N 900 760 940 760 {}
N 220 730 220 230 {}
N 220 170 220 100 {}
N 220 310 160 310 {}
N 160 310 160 200 {}
N 160 200 180 200 {}
N 160 150 160 200 {}
N 160 150 900 150 {}
N 900 150 900 200 {}
N 900 200 940 200 {}
N 980 730 980 230 {}
N 980 500 1100 500 {}
N 980 170 980 100 {}
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
N 500 200 500 1010 {}
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
C {sky130_fd_pr/pfet_01v8.sym} 560 200 0 0 {name=M1 L=0.25 W=6.06 nf=1 mult=1 ad=1.7574 as=1.7574 pd=12.7 ps=12.7 nrd=0.0478548 nrs=0.0478548 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 580 200 0 0 {name=net6 lab=vdd hide_texts=true}
T {M1} 605 182 0 0 0.29 0.29 {layer=3}
T {6.06/0.25} 605 207 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 540 200 0 0 {name=net9 lab=s1t}
C {sky130_fd_pr/pfet_01v8.sym} 700 400 0 0 {name=M2 L=0.25 W=2.21 nf=1 mult=1 ad=0.6409 as=0.6409 pd=5 ps=5 nrd=0.131222 nrs=0.131222 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 720 400 0 0 {name=net11 lab=vdd hide_texts=true}
T {M2} 745 382 0 0 0.29 0.29 {layer=3}
T {2.21/0.25} 745 407 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/pfet_01v8.sym} 460 400 0 0 {name=M3 L=0.25 W=2.21 nf=1 mult=1 ad=0.6409 as=0.6409 pd=5 ps=5 nrd=0.131222 nrs=0.131222 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 480 400 0 0 {name=net15 lab=vdd hide_texts=true}
T {M3} 505 382 0 0 0.29 0.29 {layer=3}
T {2.21/0.25} 505 407 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 580 260 0 0 {name=net18 lab=t1}
C {devices/lab_wire.sym} 640 400 0 0 {name=net19 lab=inp}
C {devices/lab_wire.sym} 400 400 0 0 {name=net20 lab=inn}
C {sky130_fd_pr/nfet_01v8.sym} 700 760 0 0 {name=M4 L=0.25 W=25.74 nf=1 mult=1 ad=7.4646 as=7.4646 pd=52.06 ps=52.06 nrd=0.0112665 nrs=0.0112665 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 720 760 0 0 {name=net22 lab=0 hide_texts=true}
T {M4} 745 742 0 0 0.29 0.29 {layer=3}
T {25.7/0.25} 745 767 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/nfet_01v8.sym} 460 760 0 0 {name=M5 L=0.25 W=25.74 nf=1 mult=1 ad=7.4646 as=7.4646 pd=52.06 ps=52.06 nrd=0.0112665 nrs=0.0112665 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 480 760 0 0 {name=net26 lab=0 hide_texts=true}
T {M5} 505 742 0 0 0.29 0.29 {layer=3}
T {25.7/0.25} 505 767 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 720 730 0 0 {name=net29 lab=x1}
C {devices/lab_wire.sym} 480 730 0 0 {name=net30 lab=x2}
C {sky130_fd_pr/nfet_01v8.sym} 240 760 0 1 {name=M6 L=0.25 W=109.26 nf=3 mult=1 ad=21.1236 as=21.1236 pd=146.84 ps=146.84 nrd=0.00265422 nrs=0.00265422 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 220 760 0 0 {name=net32 lab=0 hide_texts=true}
T {M6} 125 742 0 0 0.29 0.29 {layer=3}
T {109/0.25} 125 767 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/nfet_01v8.sym} 960 760 0 0 {name=M7 L=0.25 W=109.26 nf=3 mult=1 ad=21.1236 as=21.1236 pd=146.84 ps=146.84 nrd=0.00265422 nrs=0.00265422 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 980 760 0 0 {name=net36 lab=0 hide_texts=true}
T {M7} 1005 742 0 0 0.29 0.29 {layer=3}
T {109/0.25} 1005 767 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/pfet_01v8.sym} 200 200 0 0 {name=M8 L=0.25 W=22.28 nf=1 mult=1 ad=6.4612 as=6.4612 pd=45.14 ps=45.14 nrd=0.0130162 nrs=0.0130162 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 220 200 0 0 {name=net40 lab=vdd hide_texts=true}
T {M8} 245 182 0 0 0.29 0.29 {layer=3}
T {22.3/0.25} 245 207 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/pfet_01v8.sym} 960 200 0 0 {name=M9 L=0.25 W=22.28 nf=1 mult=1 ad=6.4612 as=6.4612 pd=45.14 ps=45.14 nrd=0.0130162 nrs=0.0130162 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 980 200 0 0 {name=net44 lab=vdd hide_texts=true}
T {M9} 1005 182 0 0 0.29 0.29 {layer=3}
T {22.3/0.25} 1005 207 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 220 730 0 0 {name=net47 lab=y1}
C {devices/lab_wire.sym} 980 730 0 0 {name=net48 lab=o1}
C {sky130_fd_pr/nfet_01v8.sym} 1440 800 0 0 {name=M10 L=0.18 W=3.71 nf=1 mult=1 ad=1.0759 as=1.0759 pd=8 ps=8 nrd=0.0781671 nrs=0.0781671 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 1460 800 0 0 {name=net50 lab=0 hide_texts=true}
T {M10} 1485 782 0 0 0.29 0.29 {layer=3}
T {3.71/0.18} 1485 807 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/nfet_01v8.sym} 1480 620 0 1 {name=M11 L=0.18 W=4.28 nf=1 mult=1 ad=1.2412 as=1.2412 pd=9.14 ps=9.14 nrd=0.067757 nrs=0.067757 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 1460 620 0 0 {name=net54 lab=0 hide_texts=true}
T {M11} 1365 602 0 0 0.29 0.29 {layer=3}
T {4.28/0.18} 1365 627 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/pfet_01v8.sym} 1480 380 0 1 {name=M12 L=0.18 W=4.28 nf=1 mult=1 ad=1.2412 as=1.2412 pd=9.14 ps=9.14 nrd=0.067757 nrs=0.067757 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 1460 380 0 0 {name=net58 lab=vdd hide_texts=true}
T {M12} 1365 362 0 0 0.29 0.29 {layer=3}
T {4.28/0.18} 1365 387 0 0 0.2 0.2 {layer=14}
C {sky130_fd_pr/pfet_01v8.sym} 1440 200 0 0 {name=M13 L=0.18 W=4.28 nf=1 mult=1 ad=1.2412 as=1.2412 pd=9.14 ps=9.14 nrd=0.067757 nrs=0.067757 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X hide_texts=true}
C {devices/lab_wire.sym} 1460 200 0 0 {name=net62 lab=vdd hide_texts=true}
T {M13} 1485 182 0 0 0.29 0.29 {layer=3}
T {4.28/0.18} 1485 207 0 0 0.2 0.2 {layer=14}
C {devices/lab_wire.sym} 1460 650 0 0 {name=net65 lab=s2a}
C {devices/lab_wire.sym} 1460 230 0 0 {name=net66 lab=s2c}
C {devices/lab_wire.sym} 1460 410 0 0 {name=net67 lab=out}
C {devices/lab_wire.sym} 1500 620 0 0 {name=net68 lab=s2cn}
C {devices/lab_wire.sym} 1500 380 0 0 {name=net69 lab=s2cp}
C {devices/vsource.sym} 500 1040 0 0 {name=V_S1T value=0.7325 m=1 hide_texts=true}
T {V_S1T} 535 1016 0 0 0.25 0.25 {layer=3}
T {0.7325} 535 1043 0 0 0.21 0.21 {layer=14}
C {devices/vsource.sym} 1680 1040 0 0 {name=V_S2CN value=0.98 m=1 hide_texts=true}
T {V_S2CN} 1715 1016 0 0 0.25 0.25 {layer=3}
T {0.98} 1715 1043 0 0 0.21 0.21 {layer=14}
C {devices/vsource.sym} 1780 1140 0 0 {name=V_S2CP value=0.435 m=1 hide_texts=true}
T {V_S2CP} 1815 1116 0 0 0.25 0.25 {layer=3}
T {0.435} 1815 1143 0 0 0.21 0.21 {layer=14}
