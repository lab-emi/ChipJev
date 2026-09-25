v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {sky130-ampN-gain chipjev seed 0: cs_n+cas_n+miller_rz} 0 -140 0 0 0.5 0.5 {}
T {ChipJev design on SKY130 (TT), VDD = 1.8 V} 0 -100 0 0 0.3 0.3 {}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=M1 L=0.6 W=2.202 nf=1 mult=1 ad=0.63858 as=0.63858 pd=4.984 ps=4.984 nrd=0.131698 nrs=0.131698 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l1 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} -20 0 0 0 {name=l2 sig_type=std_logic lab=in}
C {devices/lab_pin.sym} 20 30 0 0 {name=l3 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 20 0 0 0 {name=l4 sig_type=std_logic lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 240 0 0 0 {name=M2 L=0.6 W=6.06 nf=1 mult=1 ad=1.7574 as=1.7574 pd=12.7 ps=12.7 nrd=0.0478548 nrs=0.0478548 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 260 30 0 0 {name=l5 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} 220 0 0 0 {name=l6 sig_type=std_logic lab=s1ld}
C {devices/lab_pin.sym} 260 -30 0 0 {name=l7 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 260 0 0 0 {name=l8 sig_type=std_logic lab=vdd}
C {sky130_fd_pr/nfet_01v8.sym} 480 0 0 0 {name=M3 L=1.69667 W=30.54 nf=1 mult=1 ad=8.8566 as=8.8566 pd=61.66 ps=61.66 nrd=0.00949574 nrs=0.00949574 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 500 -30 0 0 {name=l9 sig_type=std_logic lab=s2a}
C {devices/lab_pin.sym} 460 0 0 0 {name=l10 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} 500 30 0 0 {name=l11 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 500 0 0 0 {name=l12 sig_type=std_logic lab=0}
C {sky130_fd_pr/nfet_01v8.sym} 720 0 0 0 {name=M4 L=1.69667 W=412.29 nf=9 mult=1 ad=66.4245 as=66.4245 pd=461 ps=461 nrd=0.000703388 nrs=0.000703388 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 740 -30 0 0 {name=l13 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 700 0 0 0 {name=l14 sig_type=std_logic lab=s2cn}
C {devices/lab_pin.sym} 740 30 0 0 {name=l15 sig_type=std_logic lab=s2a}
C {devices/lab_pin.sym} 740 0 0 0 {name=l16 sig_type=std_logic lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 960 0 0 0 {name=M5 L=1.69667 W=40.72 nf=1 mult=1 ad=11.8088 as=11.8088 pd=82.02 ps=82.02 nrd=0.00712181 nrs=0.00712181 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 980 30 0 0 {name=l17 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 940 0 0 0 {name=l18 sig_type=std_logic lab=s2ld}
C {devices/lab_pin.sym} 980 -30 0 0 {name=l19 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 980 0 0 0 {name=l20 sig_type=std_logic lab=vdd}
C {devices/res.sym} 1200 0 0 0 {name=R6 value=2110 m=1}
C {devices/lab_pin.sym} 1200 -30 0 0 {name=l21 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 1200 30 0 0 {name=l22 sig_type=std_logic lab=cz}
C {devices/capa.sym} 0 200 0 0 {name=C7 value=1.77e-13 m=1}
C {devices/lab_pin.sym} 0 170 0 0 {name=l23 sig_type=std_logic lab=cz}
C {devices/lab_pin.sym} 0 230 0 0 {name=l24 sig_type=std_logic lab=o1}
C {devices/vsource.sym} 240 200 0 0 {name=VDD value=1.8 m=1}
C {devices/lab_pin.sym} 240 170 0 0 {name=l25 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 240 230 0 0 {name=l26 sig_type=std_logic lab=0}
C {devices/vsource.sym} 480 200 0 0 {name=V_S1LD value=0.1725 m=1}
C {devices/lab_pin.sym} 480 170 0 0 {name=l27 sig_type=std_logic lab=s1ld}
C {devices/lab_pin.sym} 480 230 0 0 {name=l28 sig_type=std_logic lab=0}
C {devices/vsource.sym} 720 200 0 0 {name=V_S2CN value=1.085 m=1}
C {devices/lab_pin.sym} 720 170 0 0 {name=l29 sig_type=std_logic lab=s2cn}
C {devices/lab_pin.sym} 720 230 0 0 {name=l30 sig_type=std_logic lab=0}
C {devices/vsource.sym} 960 200 0 0 {name=V_S2LD value=0.68 m=1}
C {devices/lab_pin.sym} 960 170 0 0 {name=l31 sig_type=std_logic lab=s2ld}
C {devices/lab_pin.sym} 960 230 0 0 {name=l32 sig_type=std_logic lab=0}
