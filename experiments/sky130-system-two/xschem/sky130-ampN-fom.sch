v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {sky130-ampN-fom chipjev seed 0: inv+inv} 0 -140 0 0 0.5 0.5 {}
T {ChipJev design on SKY130 (TT), VDD = 1.8 V} 0 -100 0 0 0.3 0.3 {}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=M1 L=0.423333 W=3.2004 nf=1 mult=1 ad=0.928116 as=0.928116 pd=6.9808 ps=6.9808 nrd=0.0906137 nrs=0.0906137 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l1 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} -20 0 0 0 {name=l2 sig_type=std_logic lab=in}
C {devices/lab_pin.sym} 20 30 0 0 {name=l3 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 20 0 0 0 {name=l4 sig_type=std_logic lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 240 0 0 0 {name=M2 L=0.423333 W=6.604 nf=1 mult=1 ad=1.91516 as=1.91516 pd=13.788 ps=13.788 nrd=0.0439128 nrs=0.0439128 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 260 30 0 0 {name=l5 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} 220 0 0 0 {name=l6 sig_type=std_logic lab=in}
C {devices/lab_pin.sym} 260 -30 0 0 {name=l7 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 260 0 0 0 {name=l8 sig_type=std_logic lab=vdd}
C {sky130_fd_pr/nfet_01v8.sym} 480 0 0 0 {name=M3 L=0.15 W=1.755 nf=1 mult=1 ad=0.50895 as=0.50895 pd=4.09 ps=4.09 nrd=0.165242 nrs=0.165242 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 500 -30 0 0 {name=l9 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 460 0 0 0 {name=l10 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} 500 30 0 0 {name=l11 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 500 0 0 0 {name=l12 sig_type=std_logic lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 720 0 0 0 {name=M4 L=0.15 W=0.42 nf=1 mult=1 ad=0.1218 as=0.1218 pd=1.42 ps=1.42 nrd=0.690476 nrs=0.690476 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 740 30 0 0 {name=l13 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 700 0 0 0 {name=l14 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} 740 -30 0 0 {name=l15 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 740 0 0 0 {name=l16 sig_type=std_logic lab=vdd}
C {devices/vsource.sym} 960 0 0 0 {name=VDD value=1.8 m=1}
C {devices/lab_pin.sym} 960 -30 0 0 {name=l17 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 960 30 0 0 {name=l18 sig_type=std_logic lab=0}
