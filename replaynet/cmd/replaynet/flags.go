package main

import "strings"

type repeatedFlag []string

func (r *repeatedFlag) String() string {
	return strings.Join(*r, ";")
}

func (r *repeatedFlag) Set(v string) error {
	*r = append(*r, v)
	return nil
}
